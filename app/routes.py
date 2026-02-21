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
import threading
from app.pedigree.analysis import analyzer

# Blueprints
main_blueprint = Blueprint('main', __name__)

# General app configuration
logging.basicConfig(level=logging.INFO)


def _resolve_default_ibc(calculator, animal_id, preferred_algorithm=None):
    """
    Resolve default IBC for an animal with priority:
    - if both available, prefer Meuwissen-Luo
    - otherwise use whichever is available

    preferred_algorithm can be: 'both', 'meuwissen', 'traditional', or None.
    """
    animal_id = str(animal_id)

    if preferred_algorithm == 'traditional':
        try:
            return calculator.get_inbreeding_traditional(animal_id)
        except Exception:
            pass
        try:
            return calculator.get_inbreeding_meuwissen(animal_id)
        except Exception:
            return 0.0

    if preferred_algorithm in ('both', 'meuwissen', None):
        try:
            return calculator.get_inbreeding_meuwissen(animal_id)
        except Exception:
            pass
        try:
            return calculator.get_inbreeding_traditional(animal_id)
        except Exception:
            return 0.0

    try:
        return calculator.get_inbreeding_meuwissen(animal_id)
    except Exception:
        try:
            return calculator.get_inbreeding_traditional(animal_id)
        except Exception:
            return 0.0

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
            df = df.apply(lambda col: col.str.strip())
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

            # Normalize potential torzs column name variations and map boolean values
            # Ensure lowercase column keys were used earlier, so check for these names
            for col in ('torzsbak_e', 'torzskos_e', 'torzs_e'):
                if col not in df.columns:
                    df[col] = ''
                else:
                    df[col] = df[col].astype(str).str.strip().str.lower()

            # "ïgen" or "igen" should be treated as True
            def is_torzs_true(val):
                try:
                    return str(val).strip().lower() in ('ïgen', 'igen')
                except Exception:
                    return False

            # torzshim indicates 'Törzshím' status derived from the
            # specific pedigree columns torzsbak_e or torzskos_e.
            # Do NOT use the general display/filter column `torzs_e`
            # to determine torzshim — it may represent a different
            # field in some CSVs.
            df['torzshim'] = df.apply(lambda r: (
                is_torzs_true(r.get('torzsbak_e')) or
                is_torzs_true(r.get('torzskos_e'))
            ), axis=1)

            # Keep the original (normalized) torzs_e value for display and filtering
            if 'torzs_e' not in df.columns:
                df['torzs_e'] = ''

            final_df = df[[
                'animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year',
                'species', 'breed', 'farm', 'torzs_e', 'torzshim'
            ]].copy()

            # Always compute missing parents
            all_animal_ids = set(final_df['animal_id'].unique())
            all_parent_ids = set(final_df['sire_id'].dropna().unique()) | set(
                final_df['dam_id'].dropna().unique())
            missing_parents = list(all_parent_ids - all_animal_ids)

            final_df = final_df.replace({np.nan: None})

            # Intermediate progress
            yield f"event: progress\ndata: {json.dumps({'stage': 'Adatok feldolgozása', 'progress': 45})}\n\n"

            # Identify core animals for optimized Meuwissen calculation
            core_animal_ids = None
            if 'torzs_e' in final_df.columns:
                core_animals_mask = final_df['torzs_e'].astype(
                    str).str.strip().str.lower().isin(['igen', 'ïgen'])
                core_animal_ids = final_df[core_animals_mask]['animal_id'].tolist(
                )
                if not core_animal_ids:
                    core_animal_ids = None

            app.logger.info(
                f"Upload: Found {len(core_animal_ids) if core_animal_ids else 0} core animals out of {len(final_df)}")

            session_id = str(uuid.uuid4())
            calculator = None
            calc_error = None

            # Always create calculator immediately - it's now fast since Meuwissen calculation is lazy
            try:
                calculator = PedigreeCalculator(
                    final_df.copy(), core_animal_ids=core_animal_ids)
            except Exception as e:
                calc_error = e

            if not hasattr(app, 'sessions'):
                app.sessions = {}
            app.sessions[session_id] = {
                'data': final_df, 'calculator': calculator, 'missing_parents': missing_parents}

            app.logger.info(
                f"Session {session_id} stored. Total sessions: {len(app.sessions)}")
            app.logger.info(f"Session keys: {list(app.sessions.keys())}")

            end_time = time.time()
            load_time = round(end_time - start_time, 2)
            animal_count = len(final_df)

            # Final result
            yield f"event: complete\ndata: {json.dumps({
                'animal_count': animal_count,
                'load_time': load_time,
                'missing_parents': missing_parents,
                'session_id': session_id,
                'progress': 100
            })}\n\n"

        except Exception as e:
            app.logger.error(
                f"File processing error: {e}", exc_info=True)
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
        df = df.apply(lambda col: col.str.strip())

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

        # Handle torzs_e column if present
        for col in ('torzsbak_e', 'torzskos_e', 'torzs_e'):
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].astype(str).str.strip().str.lower()

        final_df = df[[
            'animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year',
            'species', 'breed', 'farm', 'torzs_e'
        ]].copy()

        all_animal_ids = set(final_df['animal_id'].unique())
        all_parent_ids = set(final_df['sire_id'].dropna().unique()) | set(
            final_df['dam_id'].dropna().unique())
        missing_parents = list(all_parent_ids - all_animal_ids)

        final_df = final_df.replace({np.nan: None})

        # Identify core animals for optimized Meuwissen calculation
        core_animal_ids = None
        if 'torzs_e' in final_df.columns:
            core_animals_mask = final_df['torzs_e'].astype(
                str).str.strip().str.lower().isin(['igen', 'ïgen'])
            core_animal_ids = final_df[core_animals_mask]['animal_id'].tolist()
            if not core_animal_ids:
                core_animal_ids = None

        session_id = str(uuid.uuid4())
        calculator = PedigreeCalculator(
            final_df.copy(), core_animal_ids=core_animal_ids)
        if not hasattr(current_app, 'sessions'):
            current_app.sessions = {}
        current_app.sessions[session_id] = {
            'data': final_df, 'calculator': calculator, 'missing_parents': missing_parents}

        end_time = time.time()
        load_time = round(end_time - start_time, 2)
        animal_count = len(final_df)

        return jsonify({
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
                current_app.sessions[session_id]['last_ibc_algorithm'] = algorithm
                core_animal_ids = None  # Initialize outside the if block

                if calculator is None:
                    # Create calculator on-demand if not precomputed
                    df_session = current_app.sessions[session_id]['data']

                    # Extract core animals for optimized Meuwissen calculation
                    core_animal_ids = None
                    if 'torzs_e' in df_session.columns:
                        core_animals_mask = df_session['torzs_e'].astype(
                            str).str.strip().str.lower().isin(['igen', 'ïgen'])
                        core_animal_ids = df_session[core_animals_mask]['animal_id'].tolist(
                        )
                        if not core_animal_ids:
                            core_animal_ids = None

                    calculator = PedigreeCalculator(
                        df_session, core_animal_ids=core_animal_ids)
                    current_app.sessions[session_id]['calculator'] = calculator
                else:
                    # If calculator already exists, get core_animal_ids from it
                    core_animal_ids = calculator.core_animal_ids

                df = calculator.df

                # Build target list for IBC calculation:
                # - if core animals exist: calculate for core animals + all their ancestors
                # - otherwise: calculate for all animals
                if 'torzs_e' in df.columns:
                    core_animals = df[df['torzs_e'].astype(str).str.strip().str.lower().isin([
                        'igen', 'ïgen'])]['animal_id'].tolist()
                else:
                    core_animals = []

                if core_animals:
                    relevant_animals = analyzer.find_all_ancestors(
                        df[['animal_id', 'sire_id', 'dam_id']].copy(),
                        core_animals,
                    )
                    # Keep dataframe order for deterministic UI updates
                    animal_ids = [
                        aid for aid in df['animal_id'].tolist() if aid in relevant_animals
                    ]
                else:
                    animal_ids = df['animal_id'].tolist()

                total_animals = len(animal_ids)

                # Log optimization info
                total_pedigree = len(df)
                core_count = len(core_animals)
                relevant_count = len(animal_ids)
                current_app.logger.info(
                    f"IBC Calculation: algorithm={algorithm}, core_animals={core_count}, relevant_animals={relevant_count}, total_pedigree={total_pedigree}, optimization_enabled={core_animal_ids is not None}")

                # For Meuwissen-Luo, stream progress during lazy matrix initialization.
                # Without this, the UI can remain on "Kapcsolódás..." for a long time.
                if algorithm in ('meuwissen', 'both') and not calculator.meuwissen_initialized:
                    ml_progress_state = {
                        'current': 0,
                        'total': 0,
                        'done': False,
                        'error': None,
                    }

                    def ml_progress_callback(current, total):
                        ml_progress_state['current'] = int(current)
                        ml_progress_state['total'] = int(total)

                    def initialize_meuwissen_cache():
                        try:
                            calculator.progress_callback = ml_progress_callback
                            calculator._ensure_meuwissen_initialized()
                        except Exception as init_exc:
                            ml_progress_state['error'] = init_exc
                        finally:
                            ml_progress_state['done'] = True

                    init_thread = threading.Thread(
                        target=initialize_meuwissen_cache,
                        daemon=True,
                    )
                    init_thread.start()

                    last_sent_progress = -1
                    while not ml_progress_state['done']:
                        total = ml_progress_state['total']
                        current = ml_progress_state['current']
                        progress = int((current / total) *
                                       100) if total > 0 else 0

                        if progress != last_sent_progress:
                            yield f"data: {json.dumps({'animal_id': 'Meuwissen-Luo előkészítés', 'progress': progress})}\n\n"
                            last_sent_progress = progress

                        time.sleep(0.2)

                    if ml_progress_state['error'] is not None:
                        raise ml_progress_state['error']

                    # Ensure progress reaches 100% for preparation phase
                    yield f"data: {json.dumps({'animal_id': 'Meuwissen-Luo előkészítés', 'progress': 100})}\n\n"
                    calculator.progress_callback = None

                for i, animal_id in enumerate(animal_ids):
                    data = {'animal_id': animal_id}
                    ibc_meuwissen_value = None
                    ibc_traditional_value = None

                    if algorithm == 'meuwissen' or algorithm == 'both':
                        ibc_meuwissen_value = calculator.get_inbreeding_meuwissen(
                            animal_id)
                        data['ibc_meuwissen'] = ibc_meuwissen_value
                    if algorithm == 'traditional' or algorithm == 'both':
                        ibc_traditional_value = calculator.get_inbreeding_traditional(
                            animal_id)
                        data['ibc_traditional'] = ibc_traditional_value

                    # Default IBC selection rule:
                    # - if both are calculated, prefer Meuwissen-Luo
                    # - otherwise use whichever is available
                    if ibc_meuwissen_value is not None:
                        data['ibc_default'] = ibc_meuwissen_value
                    elif ibc_traditional_value is not None:
                        data['ibc_default'] = ibc_traditional_value
                    else:
                        data['ibc_default'] = None

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
    current_app.logger.info(
        f"mating_selection called with session_id: {session_id}")
    current_app.logger.info(
        f"Available sessions: {list(current_app.sessions.keys())}")
    if not session_id or session_id not in current_app.sessions:
        current_app.logger.error(
            f"Session {session_id} not found in mating_selection!")
        return "Hiba: Érvénytelen vagy lejárt munkamenet.", 400
    return render_template('pedigree/mating_selection.html', session_id=session_id)


@main_blueprint.route('/pedigree/animals/<session_id>')
def get_animals(session_id):
    if not session_id or session_id not in current_app.sessions:
        return jsonify({"error": "Érvénytelen munkamenet"}), 404

    df = current_app.sessions[session_id]['data'].copy()
    calculator = current_app.sessions[session_id]['calculator']
    preferred_algorithm = current_app.sessions[session_id].get(
        'last_ibc_algorithm')

    # Safely get IBC values for each animal
    df['ibc'] = df['animal_id'].apply(
        lambda id: _resolve_default_ibc(calculator, id, preferred_algorithm))

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

    # Ensure torzshim flag exists (in case older sessions lack it)
    if 'torzshim' not in df.columns:
        for col in ('torzsbak_e', 'torzskos_e', 'torzs_e'):
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.lower()

        def _is_torzs(v):
            try:
                return str(v).strip().lower() in ('ïgen', 'igen')
            except Exception:
                return False
        # Only derive torzshim from the explicit torzsbak_e / torzskos_e
        # columns. Keep `torzs_e` only for display/filtering purposes.
        df['torzshim'] = df.apply(lambda r: (
            _is_torzs(r.get('torzsbak_e')) or
            _is_torzs(r.get('torzskos_e'))
        ), axis=1)

    # Ensure torzs_e column exists and is normalized for filtering/display
    if 'torzs_e' not in df.columns:
        df['torzs_e'] = ''
    else:
        df['torzs_e'] = df['torzs_e'].astype(str).str.strip().str.lower()

    # Define columns to return (excluding torzs_e and torzshim)
    columns_to_return = ['animal_id', 'farm', 'birth_year', 'ibc']

    # Filter only core animals (torzs_e = 'igen' or 'ïgen') and separate by gender
    def _is_torzs_core(v):
        return str(v).strip().lower() in ('igen', 'ïgen')

    core_animals = df[df['torzs_e'].apply(_is_torzs_core)]
    sires = core_animals[core_animals['gender'] == 'M'][columns_to_return].to_dict(
        orient='records')
    dams = core_animals[core_animals['gender'] ==
                        'F'][columns_to_return].to_dict(orient='records')

    # Get unique farms for sires and dams with counts
    from collections import Counter
    sire_farm_counts = Counter([s['farm'] for s in sires])
    dam_farm_counts = Counter([d['farm'] for d in dams])

    sire_farms = [{'farm': farm, 'count': sire_farm_counts[farm]}
                  for farm in sorted(sire_farm_counts.keys())]
    dam_farms = [{'farm': farm, 'count': dam_farm_counts[farm]}
                 for farm in sorted(dam_farm_counts.keys())]

    return jsonify({
        'sires': sires,
        'dams': dams,
        'sire_farms': sire_farms,
        'dam_farms': dam_farms
    })


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
    preferred_algorithm = sessions[session_id].get('last_ibc_algorithm')

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
                sire_ibc = _resolve_default_ibc(
                    calculator, sire['animal_id'], preferred_algorithm)
                for dam in dam_details:
                    dam_ibc = _resolve_default_ibc(
                        calculator, dam['animal_id'], preferred_algorithm)
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
            preferred_algorithm = current_app.sessions[session_id].get(
                'last_ibc_algorithm')

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
                sire_ibc = _resolve_default_ibc(
                    calculator, sire['animal_id'], preferred_algorithm)
                for dam in dam_details:
                    dam_ibc = _resolve_default_ibc(
                        calculator, dam['animal_id'], preferred_algorithm)
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


@main_blueprint.route('/get_data', methods=['GET'])
def get_data():
    session_id = request.args.get('session_id')
    current_app.logger.info(f"get_data called with session_id: {session_id}")
    current_app.logger.info(
        f"Available sessions: {list(current_app.sessions.keys())}")
    current_app.logger.info(f"Total sessions: {len(current_app.sessions)}")
    if not session_id or session_id not in current_app.sessions:
        current_app.logger.error(f"Session {session_id} not found!")
        return jsonify({"error": "Invalid session"}), 400
    session_data = current_app.sessions[session_id]
    data_df = session_data['data']
    missing_parents = session_data.get('missing_parents', [])
    return jsonify({
        'records': data_df.to_dict(orient='records'),
        'missing_parents': missing_parents
    })
