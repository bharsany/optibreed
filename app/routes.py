from flask import Blueprint, render_template, request, jsonify, current_app, Response, session, send_file
from flask_login import login_required
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
@login_required
def index():
    if 'user_session_id' not in session:
        session['user_session_id'] = str(uuid.uuid4())
    
    session_id = session['user_session_id']
    app = current_app._get_current_object()
    
    if not hasattr(app, 'sessions'):
        app.sessions = {}
        
    if session_id not in app.sessions:
        app.sessions[session_id] = {
            'breed': None,
            'farm': None,
            'pedigree': None,
        #   'data': df, # Used by legacy logic, we'll phase this out or alias it
            'calculator': None,
            'missing_parents': []
        }
    
    user_data = app.sessions[session_id]
    
    status = {
        'breed_loaded': user_data.get('breed') is not None,
        'farm_loaded': user_data.get('farm') is not None,
        'pedigree_loaded': user_data.get('pedigree') is not None,
        'breed_filename': user_data.get('breed_filename'),
        'farm_filename': user_data.get('farm_filename'),
        'pedigree_filename': user_data.get('pedigree_filename'),
    }

    return render_template('dashboard.html', status=status)


@main_blueprint.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Render.com"""
    return jsonify({'status': 'ok', 'sessions': len(current_app.sessions)}), 200

def _decode_and_read_csv(file_bytes_or_file):
    import io
    if hasattr(file_bytes_or_file, 'read'):
        file_bytes = file_bytes_or_file.read()
    else:
        file_bytes = file_bytes_or_file

    encodings_to_try = ['utf-8', 'windows-1250', 'iso-8859-2', 'latin1']
    for enc in encodings_to_try:
        try:
            return pd.read_csv(io.StringIO(file_bytes.decode(enc)), dtype=str)
        except UnicodeDecodeError:
            continue
    # Fallback
    return pd.read_csv(io.StringIO(file_bytes.decode('utf-8', errors='replace')), dtype=str)


def _load_reference_data(request_file_key, expected_columns, session_key, session_id):
    if request_file_key not in request.files or not request.files[request_file_key].filename:
        return "Nincs fájl kiválasztva.", 400
    
    file = request.files[request_file_key]
    try:
        df = _decode_and_read_csv(file).rename(columns=lambda x: str(x).strip().upper())
        df = df.apply(lambda col: col.str.strip())
        
        # Check against expected columns (uppercase)
        expected_set = set([c.upper() for c in expected_columns])
        if not expected_set.issubset(df.columns):
            missing = sorted(list(expected_set - set(df.columns)))
            return f"Hiányzó oszlopok: {', '.join(missing)}", 400
            
        final_df = df[list(expected_set)].copy()
        sess = current_app._get_current_object().sessions[session_id]
        sess[session_key] = final_df
        sess[f"{session_key}_filename"] = file.filename
        return None, 200
        
    except Exception as e:
        current_app.logger.error(f"Error loading {session_key}: {e}", exc_info=True)
        return f"Hiba a fájl beolvasása közben: {e}", 500


@main_blueprint.route('/upload_breed', methods=['POST'])
@login_required
def upload_breed():
    if 'user_session_id' not in session: return jsonify({'error': 'No session'}), 400
    session_id = session['user_session_id']
    err, code = _load_reference_data('breed_file', ['FAJ', 'FAJTA_KOD', 'FAJTA_NEV'], 'breed', session_id)
    if err:
        return f"<script>alert('{err}'); window.location.href='/';</script>", code
    return "<script>window.location.href='/';</script>", 200

@main_blueprint.route('/upload_farm', methods=['POST'])
@login_required
def upload_farm():
    if 'user_session_id' not in session: return jsonify({'error': 'No session'}), 400
    session_id = session['user_session_id']
    err, code = _load_reference_data('farm_file', ['TENYKOD', 'TENYNEV', 'HELYSEG', 'torzstenyeszet'], 'farm', session_id)
    if err:
        return f"<script>alert('{err}'); window.location.href='/';</script>", code
    return "<script>window.location.href='/';</script>", 200

@main_blueprint.route('/clear_breed', methods=['POST'])
@login_required
def clear_breed():
    if 'user_session_id' in session:
        session_id = session['user_session_id']
        app = current_app._get_current_object()
        if session_id in app.sessions:
            app.sessions[session_id]['breed'] = None
            app.sessions[session_id]['pedigree'] = None
            app.sessions[session_id]['calculator'] = None
            app.sessions[session_id].pop('last_simulation_results', None)
    return "<script>window.location.href='/';</script>", 200

@main_blueprint.route('/clear_farm', methods=['POST'])
@login_required
def clear_farm():
    if 'user_session_id' in session:
        session_id = session['user_session_id']
        app = current_app._get_current_object()
        if session_id in app.sessions:
            app.sessions[session_id]['farm'] = None
            app.sessions[session_id]['pedigree'] = None
            app.sessions[session_id]['calculator'] = None
            app.sessions[session_id].pop('last_simulation_results', None)
    return "<script>window.location.href='/';</script>", 200

@main_blueprint.route('/clear_pedigree', methods=['POST'])
@login_required
def clear_pedigree():
    if 'user_session_id' in session:
        session_id = session['user_session_id']
        app = current_app._get_current_object()
        if session_id in app.sessions:
            app.sessions[session_id]['pedigree'] = None
            app.sessions[session_id]['calculator'] = None
            app.sessions[session_id].pop('last_simulation_results', None)
    return "<script>window.location.href='/';</script>", 200

@main_blueprint.route('/view_pedigree', methods=['GET'])
@login_required
def view_pedigree():
    # Renders the classic index.html (renamed to pedigree.html)
    session_id = session.get('user_session_id')
    app = current_app._get_current_object()
    filename = None
    if session_id in app.sessions:
        filename = app.sessions[session_id].get('pedigree_filename')
    return render_template('pedigree.html', session_id=session_id, filename=filename)

@main_blueprint.route('/view_breeds', methods=['GET'])
@login_required
def view_breeds():
    session_id = session.get('user_session_id')
    app = current_app._get_current_object()
    filename = None
    if session_id in app.sessions:
        filename = app.sessions[session_id].get('breed_filename')
    return render_template('breeds.html', filename=filename)

@main_blueprint.route('/view_farms', methods=['GET'])
@login_required
def view_farms():
    session_id = session.get('user_session_id')
    app = current_app._get_current_object()
    filename = None
    if session_id in app.sessions:
        filename = app.sessions[session_id].get('farm_filename')
    return render_template('farms.html', filename=filename)

@main_blueprint.route('/api/breeds', methods=['GET'])
@login_required
def api_breeds():
    if 'user_session_id' not in session: return jsonify([]), 400
    session_id = session['user_session_id']
    app = current_app._get_current_object()
    if session_id in app.sessions and app.sessions[session_id].get('breed') is not None:
        df = app.sessions[session_id]['breed'].copy()
        df = df.replace({np.nan: None})
        return jsonify({'records': df.to_dict(orient='records')})
    return jsonify({'records': []})

@main_blueprint.route('/api/farms', methods=['GET'])
@login_required
def api_farms():
    if 'user_session_id' not in session: return jsonify([]), 400
    session_id = session['user_session_id']
    app = current_app._get_current_object()
    if session_id in app.sessions and app.sessions[session_id].get('farm') is not None:
        df = app.sessions[session_id]['farm'].copy()
        df = df.replace({np.nan: None})
        return jsonify({'records': df.to_dict(orient='records')})
    return jsonify({'records': []})

@main_blueprint.route('/upload_and_process_stream', methods=['POST'])
@login_required
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
    file_obj = request.files['pedigree_file']
    filename = file_obj.filename
    file_content = file_obj.read()
    app = current_app._get_current_object()
    session_id = session.get('user_session_id')

    def generate_upload_stream():
        from io import BytesIO, StringIO
        try:
            start_time = time.time()
            
            if not session_id:
                yield f"event: error\ndata: {json.dumps({'error': 'Nincs munkamenet.'})}\n\n"
                return
                
            if not hasattr(app, 'sessions') or session_id not in app.sessions:
                yield f"event: error\ndata: {json.dumps({'error': 'Érvénytelen munkamenet.'})}\n\n"
                return
                
            sess_data = app.sessions[session_id]
            if sess_data.get('breed') is None or sess_data.get('farm') is None:
                yield f"event: error\ndata: {json.dumps({'error': 'A fajta és tenyészet szótárakat előbb fel kell tölteni!'})}\n\n"
                return

            breed_df = sess_data['breed']
            farm_df = sess_data['farm']

            # Step 1: Read CSV with progress
            yield f"event: progress\ndata: {json.dumps({'stage': 'CSV betöltés', 'progress': 0})}\n\n"

            # Convert bytes to DataFrame with resilient encoding
            df = _decode_and_read_csv(file_content).rename(
                columns=lambda x: str(x).strip().lower())
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

            # Join with Breed Dictionary
            # Pedigree files usually have 'species' matches FAJ and 'breed' matches FAJTA_KOD
            # Ensure types match for merging (strings)
            df['species'] = df['species'].astype(str)
            df['breed'] = df['breed'].astype(str)
            
            # Use left merge to keep all pedigree rows even if dictionary is missing some
            # But normally we expect a full dictionary
            df = df.merge(
                breed_df[['FAJ', 'FAJTA_KOD', 'FAJTA_NEV']], 
                how='left', 
                left_on=['species', 'breed'], 
                right_on=['FAJ', 'FAJTA_KOD']
            )

            # Join with Farm Dictionary
            df['farm'] = df['farm'].astype(str)
            df = df.merge(
                farm_df[['TENYKOD', 'TENYNEV', 'HELYSEG', 'TORZSTENYESZET']],
                how='left',
                left_on='farm',
                right_on='TENYKOD'
            )

            # Store the joined names back to 'farm' for display backward compatibility, 
            # and append locality. Or store standard and new columns.
            
            # Clean up boolean for core farm (Törzstenyészet)
            if 'torzs_e' not in df.columns:
                df['torzs_e'] = df['TORZSTENYESZET'].fillna('').astype(str).str.strip().str.lower()
                
            final_df = df[[
                'animal_id', 'sire_id', 'dam_id', 'gender', 'birth_year',
                'species', 'breed', 'FAJTA_NEV', 'farm', 'TENYNEV', 'HELYSEG', 
                'torzs_e', 'torzshim'
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
            if session_id not in app.sessions:
                app.sessions[session_id] = {}
                
            app.sessions[session_id]['data'] = final_df
            app.sessions[session_id]['pedigree'] = final_df
            app.sessions[session_id]['pedigree_filename'] = filename
            app.sessions[session_id]['calculator'] = calculator
            app.sessions[session_id]['missing_parents'] = missing_parents

            app.logger.info(
                f"Session {session_id} updated. Total sessions: {len(app.sessions)}")

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
@login_required
def upload_and_process():
    return jsonify({"error": "Ez a végpont már nem támogatott, kérjük használja a streamelt verziót."}), 400


@main_blueprint.route('/calculate_ibcs')
@login_required
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

                # Get the session DataFrame reference so we can persist IBC values
                session_df = current_app.sessions[session_id]['data']

                # Ensure IBC columns exist in the DataFrame
                for col in ['ibc_meuwissen', 'ibc_traditional', 'ibc_default']:
                    if col not in session_df.columns:
                        session_df[col] = None

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

                    # Persist IBC values back into the session DataFrame
                    mask = session_df['animal_id'] == animal_id
                    if mask.any():
                        if ibc_meuwissen_value is not None:
                            session_df.loc[mask, 'ibc_meuwissen'] = ibc_meuwissen_value
                        if ibc_traditional_value is not None:
                            session_df.loc[mask, 'ibc_traditional'] = ibc_traditional_value
                        if data['ibc_default'] is not None:
                            session_df.loc[mask, 'ibc_default'] = data['ibc_default']

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
@login_required
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
@login_required
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
        # Map farm ID to Farm Name if farm dictionary is loaded
        if 'farm' in current_app.sessions[session_id] and current_app.sessions[session_id]['farm'] is not None:
            farm_dict_df = current_app.sessions[session_id]['farm']
            if 'TENYKOD' in farm_dict_df.columns and 'TENYNEV' in farm_dict_df.columns:
                # Create a mapping dictionary {TENYKOD: TENYNEV}
                farm_map = dict(zip(farm_dict_df['TENYKOD'], farm_dict_df['TENYNEV']))
                df['farm'] = df['farm'].map(farm_map).fillna(df['farm'])

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
@login_required
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
            download_name='parositas_eredmenyek.xlsx',
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        current_app.logger.error(f"Hiba az eredmények exportálásakor: {e}", exc_info=True)
        return "Hiba történt az exportálás során.", 500


from xhtml2pdf import pisa
from datetime import datetime
from flask_login import current_user

@main_blueprint.route('/pedigree/export_pdf', methods=['POST'])
@login_required
def export_pdf():
    data = request.get_json()
    if not data or 'pairings' not in data:
        return "Hiba: Hiányzó adatok az exportáláshoz.", 400

    try:
        pairings_data = data['pairings']
        
        # Group pairings by sire to generate the summary matching the frontend view
        from collections import defaultdict
        sire_summary = defaultdict(list)
        
        for p in pairings_data:
            sire_id = p.get('sire_id')
            sire_summary[sire_id].append(p)
            
        summary_data = []
        for sire_id, parings in sire_summary.items():
            ibcs = [float(p['offspring_ibc']) for p in parings if 'offspring_ibc' in p]
            if ibcs:
                avg_ibc = sum(ibcs) / len(ibcs)
                min_ibc = min(ibcs)
                max_ibc = max(ibcs)
                
                # Fetch sire details from the first pairing
                first = parings[0]
                summary_data.append({
                    'sire_id': sire_id,
                    'sire_farm': first.get('sire_farm', ''),
                    'sire_birth_year': first.get('sire_birth_year', ''),
                    'sire_ibc': float(first.get('sire_ibc', 0)),
                    'avg_offspring_ibc': avg_ibc,
                    'min_offspring_ibc': min_ibc,
                    'max_offspring_ibc': max_ibc
                })
        
        # Sort by average offspring IBC descending (optional)
        summary_data.sort(key=lambda x: x['avg_offspring_ibc'])
        lowest_avg = summary_data[0]['avg_offspring_ibc'] if summary_data else 0

        # Extract unique dams for the report parameters
        # Extract unique dams for the report parameters
        unique_dams_map = {}
        for p in pairings_data:
            dam_id = p.get('dam_id')
            if dam_id and dam_id not in unique_dams_map:
                unique_dams_map[dam_id] = {
                    'dam_id': dam_id,
                    'dam_farm': p.get('dam_farm', ''),
                    'dam_birth_year': p.get('dam_birth_year', ''),
                    'dam_ibc': float(p.get('dam_ibc', 0))
                }
        unique_dams = list(unique_dams_map.values())
        unique_dams.sort(key=lambda x: str(x['dam_id']))

        import os
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        
        # Use the included Roboto font to support Latin Extended characters,
        # which works across both Windows and Linux deployments.
        import os
        from flask import current_app
        raw_font_path = os.path.join(current_app.root_path, 'static', 'Roboto-Regular.ttf')
        pdfmetrics.registerFont(TTFont('CustomArial', raw_font_path))

        # Render HTML string
        html_string = render_template(
            'pedigree/pdf_report.html',
            summary_data=summary_data,
            lowest_avg=lowest_avg,
            unique_dams=unique_dams,
            current_user=current_user,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        # Create PDF without link_callback since we registered the font directly
        pdf_stream = BytesIO()
        pisa_status = pisa.CreatePDF(html_string, dest=pdf_stream, encoding='utf-8')
        
        if pisa_status.err:
            return "Hiba a PDF generálása során.", 500
            
        pdf_stream.seek(0)
        
        return send_file(
            pdf_stream,
            download_name=f'parositas_eredmenyek_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
            as_attachment=True,
            mimetype='application/pdf'
        )

    except Exception as e:
        current_app.logger.error(f"Hiba a PDF exportálásakor: {e}", exc_info=True)
        return "Hiba történt a PDF exportálás során.", 500


@main_blueprint.route('/pedigree/simulation_results_stream', methods=['POST'])
@login_required
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

    if 'farm' not in df.columns:
        df['farm'] = 'Ismeretlen'
    else:
        if 'farm' in current_app.sessions[session_id] and current_app.sessions[session_id]['farm'] is not None:
            farm_dict_df = current_app.sessions[session_id]['farm']
            if 'TENYKOD' in farm_dict_df.columns and 'TENYNEV' in farm_dict_df.columns:
                farm_map = dict(zip(farm_dict_df['TENYKOD'], farm_dict_df['TENYNEV']))
                df['farm'] = df['farm'].map(farm_map).fillna(df['farm'])

        df['farm'] = df['farm'].fillna('Ismeretlen')

    if 'birth_year' not in df.columns:
        df['birth_year'] = 'Ismeretlen'
    else:
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
@login_required
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

            if 'farm' not in df.columns:
                df['farm'] = 'Ismeretlen'
            else:
                if 'farm' in current_app.sessions[session_id] and current_app.sessions[session_id]['farm'] is not None:
                    farm_dict_df = current_app.sessions[session_id]['farm']
                    if 'TENYKOD' in farm_dict_df.columns and 'TENYNEV' in farm_dict_df.columns:
                        farm_map = dict(zip(farm_dict_df['TENYKOD'], farm_dict_df['TENYNEV']))
                        df['farm'] = df['farm'].map(farm_map).fillna(df['farm'])

                df['farm'] = df['farm'].fillna('Ismeretlen')

            if 'birth_year' not in df.columns:
                df['birth_year'] = 'Ismeretlen'
            else:
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

        return render_template('pedigree/simulation_result.html', results=results_data, session_id=session_id)

    except Exception as e:
        current_app.logger.error(
            f"Error in simulation results: {e}", exc_info=True)
        return "Hiba a szimulációs eredmények generálása során.", 500


@main_blueprint.route('/get_data', methods=['GET'])
@login_required
def get_data():
    session_id = request.args.get('session_id')
    current_app.logger.info(f"get_data called with session_id: {session_id}")
    current_app.logger.info(
        f"Available sessions: {list(current_app.sessions.keys())}")
    current_app.logger.info(f"Total sessions: {len(current_app.sessions)}")

    if not session_id:
        current_app.logger.error("No session_id provided!")
        return jsonify({"error": "Missing session_id parameter"}), 400

    if session_id not in current_app.sessions:
        current_app.logger.error(
            f"Session {session_id} not found in {len(current_app.sessions)} available sessions!")
        # Try to provide helpful error info
        return jsonify({
            "error": f"Session not found (looking for: {session_id[:8]}...)",
            "available_sessions_count": len(current_app.sessions)
        }), 404

    try:
        session_data = current_app.sessions[session_id]
        if 'data' not in session_data:
            current_app.logger.error(
                f"Session {session_id} exists but has no 'data' key!")
            return jsonify({"error": "Session data corrupted"}), 500

        data_df = session_data['data'].copy()
        data_df = data_df.replace({np.nan: None})
        missing_parents = session_data.get('missing_parents', [])

        return jsonify({
            'records': data_df.to_dict(orient='records'),
            'missing_parents': missing_parents
        })
    except Exception as e:
        current_app.logger.error(f"Error in get_data: {e}", exc_info=True)
        return jsonify({"error": f"Error retrieving data: {str(e)}"}), 500
