from flask import Blueprint, render_template, request, jsonify, current_app, Response, session, send_file
import pandas as pd
import numpy as np
import json
import os
import uuid
from app.pedigree.calculator import PedigreeCalculator
import logging
from io import BytesIO
import time

# Blueprints
main_blueprint = Blueprint('main', __name__)

# General app configuration
logging.basicConfig(level=logging.INFO)

# --- Main Blueprint Routes (Core App) ---


@main_blueprint.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@main_blueprint.route('/upload_and_process_stream', methods=['POST'])
def upload_and_process_stream():
    """
    Streams progress updates during CSV upload and IBC pre-calculation.
    Emits SSE events with progress information.
    """
    if 'pedigree_file' not in request.files or not request.files['pedigree_file'].filename:
        return Response(
            f"event: error\ndata: {json.dumps({'error': 'Nincs fájl kiválasztva.'})}\n\n",
            mimetype='text/event-stream'
        )

    # Read file inside request context (before creating generator)
    file_content = request.files['pedigree_file'].read()
    app = current_app._get_current_object()

    def generate_upload_stream():
        from io import BytesIO, StringIO
        try:
            start_time = time.time()

            # Step 1: Read CSV with progress
            yield f"event: progress\ndata: {json.dumps({'stage': 'CSV betöltés', 'progress': 0})}\n\n"

            # Convert bytes to StringIO for pandas
            df = pd.read_csv(StringIO(file_content.decode('utf-8')), dtype=str).rename(
                columns=lambda x: x.strip().lower())
            yield f"event: progress\ndata: {json.dumps({'stage': 'CSV betöltés', 'progress': 25, 'rows': len(df)})}\n\n"

            # Step 2: Validate columns
            expected_columns = {
                "faj", "fajta", "orszagkod", "fulszam", "szuletesi_ev", "ivar_kod",
                "apaorsko", "apafulszam", "anyaorsko", "anyafulsza", "tenyeszet"
            }
            if not expected_columns.issubset(df.columns):
                missing = sorted(list(expected_columns - set(df.columns)))
                yield f"event: error\ndata: {json.dumps({'error': f'Hiányzó oszlopok: {', '.join(missing)}'})}\n\n"
                return

            # Step 3: Data processing (composite IDs, etc.)
            yield f"event: progress\ndata: {json.dumps({'stage': 'Adatok feldolgozása', 'progress': 40})}\n\n"

            df['animal_id'] = df['orszagkod'].fillna(
                '') + df['fulszam'].fillna('')
            df['sire_id'] = df['apaorsko'].fillna(
                '') + df['apafulszam'].fillna('')
            df['dam_id'] = df['anyaorsko'].fillna(
                '') + df['anyafulsza'].fillna('')

            df['sire_id'] = df['sire_id'].replace('', None)
            df['dam_id'] = df['dam_id'].replace('', None)

            df['ivar_kod'] = pd.to_numeric(df['ivar_kod'], errors='coerce')
            df['gender'] = df['ivar_kod'].map({1: 'M', 2: 'F'})

            df.rename(columns={
                'szuletesi_ev': 'birth_year',
                'faj': 'species',
                'fajta': 'breed',
                'tenyeszet': 'farm'
            }, inplace=True)

            final_df = df[[
                'animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year',
                'species', 'breed', 'farm'
            ]].copy()

            all_animal_ids = set(final_df['animal_id'].unique())
            all_parent_ids = set(final_df['sire_id'].dropna().unique()) | set(
                final_df['dam_id'].dropna().unique())
            missing_parents = list(all_parent_ids - all_animal_ids)

            final_df = final_df.replace({np.nan: None})

            # Intermediate progress
            yield f"event: progress\ndata: {json.dumps({'stage': 'Adatok feldolgozása', 'progress': 45})}\n\n"

            # Use threading to allow progress events to be yielded as they're generated
            # during the calculator initialization (which is the slow step)
            import threading
            from queue import Queue

            progress_queue = Queue()
            session_id = str(uuid.uuid4())
            calculator = None
            calc_error = None

            def create_calculator():
                nonlocal calculator, calc_error
                try:
                    def stream_progress(current, total):
                        percent = 50 + int((current / total) * 50)
                        progress_queue.put(
                            ('progress', current, total, percent))

                    calculator = PedigreeCalculator(
                        final_df.copy(), progress_callback=stream_progress)
                    progress_queue.put(('done', None, None, None))
                except Exception as e:
                    calc_error = e
                    progress_queue.put(('error', str(e), None, None))

            # Start calculator init in background thread
            calc_thread = threading.Thread(
                target=create_calculator, daemon=True)
            calc_thread.start()

            # Yield progress events as they're generated
            # Keep checking the queue and yielding events until we get 'done' or 'error'
            while True:
                try:
                    event_type, *event_data = progress_queue.get(timeout=0.5)
                    if event_type == 'progress':
                        current, total, percent = event_data
                        yield f"event: progress\ndata: {json.dumps({'stage': f'Szülők közötti kapcsolatok számítása ({current}/{total})', 'progress': percent})}\n\n"
                    elif event_type == 'done':
                        break
                    elif event_type == 'error':
                        raise Exception(event_data[0])
                except:
                    # Timeout - check if thread is still alive
                    if not calc_thread.is_alive():
                        # Thread finished, check for error
                        if calc_error:
                            raise calc_error
                        break

            # Wait for calculator thread to finish (should be quick now)
            calc_thread.join(timeout=5)
            if calc_error:
                raise calc_error

            if not hasattr(app, 'sessions'):
                app.sessions = {}
            app.sessions[session_id] = {
                'data': final_df, 'calculator': calculator}

            end_time = time.time()
            load_time = round(end_time - start_time, 2)
            animal_count = len(final_df)

            # Final result
            yield f"event: complete\ndata: {json.dumps({
                'records': final_df.to_dict(orient='records'),
                'animal_count': animal_count,
                'load_time': load_time,
                'missing_parents': missing_parents,
                'session_id': session_id,
                'progress': 100
            })}\n\n"

        except Exception as e:
            app.logger.error(f"File processing error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': f'Hiba a fájl feldolgozása közben: {str(e)}'})}\n\n"

    return Response(generate_upload_stream(), mimetype='text/event-stream')


@main_blueprint.route('/upload_and_process', methods=['POST'])
def upload_and_process():
    if 'pedigree_file' not in request.files or not request.files['pedigree_file'].filename:
        return jsonify({"error": "Nincs fájl kiválasztva."}), 400

    file = request.files['pedigree_file']
    start_time = time.time()
    try:
        df = pd.read_csv(file, dtype=str).rename(
            columns=lambda x: x.strip().lower())

        expected_columns = {
            "faj", "fajta", "orszagkod", "fulszam", "szuletesi_ev", "ivar_kod",
            "apaorsko", "apafulszam", "anyaorsko", "anyafulsza", "tenyeszet"
        }
        if not expected_columns.issubset(df.columns):
            missing = sorted(list(expected_columns - set(df.columns)))
            return jsonify({"error": f"Hiányzó oszlopok: {', '.join(missing)}"}), 400

        df['animal_id'] = df['orszagkod'].fillna('') + df['fulszam'].fillna('')
        df['sire_id'] = df['apaorsko'].fillna('') + df['apafulszam'].fillna('')
        df['dam_id'] = df['anyaorsko'].fillna('') + df['anyafulsza'].fillna('')

        df['sire_id'] = df['sire_id'].replace('', None)
        df['dam_id'] = df['dam_id'].replace('', None)

        df['ivar_kod'] = pd.to_numeric(df['ivar_kod'], errors='coerce')
        df['gender'] = df['ivar_kod'].map({1: 'M', 2: 'F'})

        df.rename(columns={
            'szuletesi_ev': 'birth_year',
            'faj': 'species',
            'fajta': 'breed',
            'tenyeszet': 'farm'
        }, inplace=True)

        final_df = df[[
            'animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year',
            'species', 'breed', 'farm'
        ]].copy()

        all_animal_ids = set(final_df['animal_id'].unique())
        all_parent_ids = set(final_df['sire_id'].dropna().unique()) | set(
            final_df['dam_id'].dropna().unique())
        missing_parents = list(all_parent_ids - all_animal_ids)

        final_df = final_df.replace({np.nan: None})

        session_id = str(uuid.uuid4())
        calculator = PedigreeCalculator(final_df.copy())
        if not hasattr(current_app, 'sessions'):
            current_app.sessions = {}
        current_app.sessions[session_id] = {
            'data': final_df, 'calculator': calculator}

        end_time = time.time()
        load_time = round(end_time - start_time, 2)
        animal_count = len(final_df)

        return jsonify({
            'records': final_df.to_dict(orient='records'),
            'animal_count': animal_count,
            'load_time': load_time,
            'missing_parents': missing_parents,
            'session_id': session_id
        })

    except Exception as e:
        current_app.logger.error(f"File processing error: {e}", exc_info=True)
        return jsonify({"error": f"Hiba a fájl feldolgozása közben: {e}"}), 500


@main_blueprint.route('/calculate_ibcs')
def calculate_ibcs_route():
    session_id = request.args.get('session_id')
    algorithm = request.args.get('algorithm', 'both')
    if not session_id or session_id not in current_app.sessions:
        return Response("Hiba: Érvénytelen vagy lejárt munkamenet.", status=400)

    app = current_app._get_current_object()

    def generate_results_stream():
        with app.app_context():
            start_time = time.time()
            try:
                calculator = current_app.sessions[session_id]['calculator']
                animal_ids = calculator.df['animal_id'].tolist()
                total_animals = len(animal_ids)

                for i, animal_id in enumerate(animal_ids):
                    data = {'animal_id': animal_id}

                    if algorithm == 'meuwissen' or algorithm == 'both':
                        data['ibc_meuwissen'] = calculator.get_inbreeding_meuwissen(
                            animal_id)
                    if algorithm == 'traditional' or algorithm == 'both':
                        data['ibc_traditional'] = calculator.get_inbreeding_traditional(
                            animal_id)

                    progress = int(((i + 1) / total_animals) * 100)
                    data['progress'] = progress

                    yield f"data: {json.dumps(data)}\n\n"

                end_time = time.time()
                calculation_time = round(end_time - start_time, 2)
                yield f"event: complete\ndata: {json.dumps({'message': 'A számítás befejeződött.', 'calculation_time': calculation_time})}\n\n"

            except Exception as e:
                current_app.logger.error(
                    f"Calculation error in stream: {e}", exc_info=True)
                error_message = f'Hiba történt a számítás során: {str(e)}'
                yield f"event: error\ndata: {json.dumps({'error': error_message})}\n\n"

    return Response(generate_results_stream(), mimetype='text/event-stream')


@main_blueprint.route('/pedigree/mating_selection')
def mating_selection():
    session_id = request.args.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return "Hiba: Érvénytelen vagy lejárt munkamenet.", 400
    return render_template('pedigree/mating_selection.html', session_id=session_id)


@main_blueprint.route('/pedigree/animals/<session_id>')
def get_animals(session_id):
    if not session_id or session_id not in current_app.sessions:
        return jsonify({"error": "Érvénytelen munkamenet"}), 404

    df = current_app.sessions[session_id]['data'].copy()
    calculator = current_app.sessions[session_id]['calculator']

    # Safely get IBC values for each animal
    df['ibc'] = df['animal_id'].apply(
        lambda id: calculator.get_inbreeding_meuwissen(id))

    # Standardize and fill missing values for farm and birth_year
    if 'farm' not in df.columns:
        df['farm'] = 'Ismeretlen'
    else:
        df['farm'] = df['farm'].fillna('Ismeretlen')

    if 'birth_year' not in df.columns:
        df['birth_year'] = 'Ismeretlen'
    else:
        df['birth_year'] = df['birth_year'].fillna('Ismeretlen')

    # Ensure 'gender' column exists and is properly formatted
    if 'gender' not in df.columns:
        dam_ids = df['dam_id'].dropna().unique()
        sire_ids = df['sire_id'].dropna().unique()
        df['gender'] = 'U'
        df.loc[df['animal_id'].isin(dam_ids), 'gender'] = 'F'
        df.loc[df['animal_id'].isin(sire_ids), 'gender'] = 'M'

    df['gender'] = df['gender'].astype(str).str.upper()

    # Define columns to return
    columns_to_return = ['animal_id', 'farm', 'birth_year', 'ibc']

    # Separate sires and dams
    sires = df[df['gender'] == 'M'][columns_to_return].to_dict(
        orient='records')
    dams = df[df['gender'] == 'F'][columns_to_return].to_dict(orient='records')

    return jsonify({'sires': sires, 'dams': dams})


@main_blueprint.route('/pedigree/export_results', methods=['POST'])
def export_results():
    data = request.get_json()
    if not data or 'pairings' not in data:
        return "Hiba: Hiányzó adatok az exportáláshoz.", 400

    try:
        pairings_data = data['pairings']

        output_df = pd.DataFrame(pairings_data)

        output_df.rename(columns={
            'sire_id': 'Apa Azonosító',
            'sire_farm': 'Apa Tenyészet',
            'sire_birth_year': 'Apa Szül. Év',
            'sire_ibc': 'Apa BTE',
            'dam_id': 'Anya Azonosító',
            'dam_farm': 'Anya Tenyészet',
            'dam_birth_year': 'Anya Szül. Év',
            'dam_ibc': 'Anya BTE',
            'offspring_ibc': 'Várható Utód BTE'
        }, inplace=True)

        final_columns = [
            'Apa Azonosító', 'Apa Tenyészet', 'Apa Szül. Év', 'Apa BTE',
            'Anya Azonosító', 'Anya Tenyészet', 'Anya Szül. Év', 'Anya BTE',
            'Várható Utód BTE'
        ]
        output_df = output_df[final_columns]

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            output_df.to_excel(writer, index=False,
                               sheet_name='Párosítási Eredmények')
        output.seek(0)

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='szimulacios_eredmenyek.xlsx'
        )

    except Exception as e:
        current_app.logger.error(
            f"Error exporting results: {e}", exc_info=True)
        return "Hiba az exportálás során.", 500


@main_blueprint.route('/pedigree/simulation_results_stream', methods=['POST'])
def simulation_results_stream():
    """
    Streams mating simulation results with progress updates.
    Sends progress events as each sire-dam pair is calculated.
    Stores results in session for later retrieval.
    """
    session_id = request.form.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return Response(
            f"event: error\ndata: {json.dumps({'error': 'Érvénytelen vagy lejárt munkamenet.'})}\n\n",
            mimetype='text/event-stream'
        )

    # Capture app and data before generator runs (while in app context)
    app = current_app._get_current_object()
    df = current_app.sessions[session_id]['data'].copy()
    calculator = current_app.sessions[session_id]['calculator']
    sessions = current_app.sessions
    
    df['farm'] = df['farm'].fillna('Ismeretlen')
    df['birth_year'] = df['birth_year'].fillna('Ismeretlen')

    sire_ids = [id for id in request.form.get('sire_ids', '').split(',') if id]
    dam_ids = [id for id in request.form.get('dam_ids', '').split(',') if id]

    sire_details = df[df['animal_id'].isin(sire_ids)].to_dict('records')
    dam_details = df[df['animal_id'].isin(dam_ids)].to_dict('records')

    def generate_simulation_stream():
        try:
            total_pairs = len(sire_details) * len(dam_details)
            results_data = []
            pair_count = 0

            yield f"event: progress\ndata: {json.dumps({'current': 0, 'total': total_pairs, 'progress': 0})}\n\n"

            for sire in sire_details:
                sire_ibc = calculator.get_inbreeding_meuwissen(
                    sire['animal_id'])
                for dam in dam_details:
                    dam_ibc = calculator.get_inbreeding_meuwissen(
                        dam['animal_id'])
                    offspring_ibc = calculator.calculate_coancestry(
                        sire['animal_id'], dam['animal_id'])
                    results_data.append({
                        'sire_id': sire['animal_id'],
                        'sire_farm': sire['farm'],
                        'sire_birth_year': sire['birth_year'],
                        'sire_ibc': sire_ibc,
                        'dam_id': dam['animal_id'],
                        'dam_farm': dam['farm'],
                        'dam_birth_year': dam['birth_year'],
                        'dam_ibc': dam_ibc,
                        'offspring_ibc': offspring_ibc
                    })
                    pair_count += 1
                    progress_percent = int((pair_count / total_pairs) * 100)
                    yield f"event: progress\ndata: {json.dumps({'current': pair_count, 'total': total_pairs, 'progress': progress_percent})}\n\n"

            # Store results in session for later retrieval
            sessions[session_id]['last_simulation_results'] = results_data

            yield f"event: complete\ndata: {json.dumps({'event': 'complete', 'data': results_data})}\n\n"

        except Exception as e:
            app.logger.error(f"Simulation error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': f'Hiba a szimuláció során: {str(e)}'})}\n\n"

    return Response(generate_simulation_stream(), mimetype='text/event-stream')


@main_blueprint.route('/pedigree/simulation_results', methods=['POST', 'GET'])
def simulation_results():
    session_id = request.args.get(
        'session_id') or request.form.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return "Hiba: Érvénytelen vagy lejárt munkamenet.", 400

    try:
        # Check if we have pre-computed results from streaming endpoint
        if 'last_simulation_results' in current_app.sessions[session_id]:
            results_data = current_app.sessions[session_id]['last_simulation_results']
        else:
            # Fallback: compute results (for POST requests from non-streaming forms)
            df = current_app.sessions[session_id]['data'].copy()
            calculator = current_app.sessions[session_id]['calculator']

            df['farm'] = df['farm'].fillna('Ismeretlen')
            df['birth_year'] = df['birth_year'].fillna('Ismeretlen')

            sire_ids = [id for id in request.form.get(
                'sire_ids', '').split(',') if id]
            dam_ids = [id for id in request.form.get(
                'dam_ids', '').split(',') if id]

            sire_details = df[df['animal_id'].isin(
                sire_ids)].to_dict('records')
            dam_details = df[df['animal_id'].isin(dam_ids)].to_dict('records')

            results_data = []
            for sire in sire_details:
                sire_ibc = calculator.get_inbreeding_meuwissen(
                    sire['animal_id'])
                for dam in dam_details:
                    dam_ibc = calculator.get_inbreeding_meuwissen(
                        dam['animal_id'])
                    offspring_ibc = calculator.calculate_coancestry(
                        sire['animal_id'], dam['animal_id'])
                    results_data.append({
                        'sire_id': sire['animal_id'],
                        'sire_farm': sire['farm'],
                        'sire_birth_year': sire['birth_year'],
                        'sire_ibc': sire_ibc,
                        'dam_id': dam['animal_id'],
                        'dam_farm': dam['farm'],
                        'dam_birth_year': dam['birth_year'],
                        'dam_ibc': dam_ibc,
                        'offspring_ibc': offspring_ibc
                    })

        return render_template('pedigree/simulation_result.html', results=results_data)

    except Exception as e:
        current_app.logger.error(
            f"Error in simulation results: {e}", exc_info=True)
        return "Hiba a szimulációs eredmények generálása során.", 500
