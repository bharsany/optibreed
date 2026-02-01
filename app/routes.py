from flask import Blueprint, render_template, request, jsonify, current_app, Response, session, send_file
import pandas as pd
import json
import os
import uuid
from app.pedigree.calculator import PedigreeCalculator
import logging
from io import BytesIO

# Blueprints
main_blueprint = Blueprint('main', __name__)

# General app configuration
logging.basicConfig(level=logging.INFO)

# --- Main Blueprint Routes (Core App) ---

@main_blueprint.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@main_blueprint.route('/upload_and_process', methods=['POST'])
def upload_and_process():
    if 'pedigree_file' not in request.files or not request.files['pedigree_file'].filename:
        return jsonify({"error": "Nincs fájl kiválasztva."}), 400

    file = request.files['pedigree_file']
    try:
        df = pd.read_csv(file)
        df = df.rename(columns=lambda x: x.strip().lower().replace(" ", "_"))
        expected_columns = {'animal_id', 'sire_id', 'dam_id'}
        if not expected_columns.issubset(df.columns):
            missing = sorted(list(expected_columns - set(df.columns)))
            return jsonify({"error": f"Hiányzó oszlopok: {', '.join(missing)}"}), 400
        
        for col in ['sire_id', 'dam_id']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        
        return jsonify(df.to_dict(orient='records'))

    except Exception as e:
        current_app.logger.error(f"File processing error: {e}", exc_info=True)
        return jsonify({"error": f"Hiba a fájl feldolgozása közben: {e}"}), 500

@main_blueprint.route('/start_calculation', methods=['POST'])
def start_calculation():
    data = request.get_json()
    if not data:
        return jsonify({"error": 'Nincs adat a számításhoz.'}), 400
    
    try:
        session_id = str(uuid.uuid4())
        df = pd.DataFrame(data)
        calculator = PedigreeCalculator(df)
        current_app.sessions[session_id] = {'data': df, 'calculator': calculator}
        return jsonify({'session_id': session_id})
    except Exception as e:
        current_app.logger.error(f"Error starting calculation: {e}")
        return jsonify({'error': 'Szerverhiba a számítás előkészítésekor.'}), 500

@main_blueprint.route('/calculate_ibcs')
def calculate_ibcs_route():
    session_id = request.args.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return Response("Hiba: Érvénytelen vagy lejárt munkamenet.", status=400)

    app = current_app._get_current_object()

    def generate_results_stream():
        with app.app_context():
            try:
                calculator = current_app.sessions[session_id]['calculator']
                animal_ids = calculator.df['animal_id'].tolist()
                total_animals = len(animal_ids)

                for i, animal_id in enumerate(animal_ids):
                    ibc_meuwissen = calculator.get_inbreeding_meuwissen(animal_id)
                    ibc_traditional = calculator.get_inbreeding_traditional(animal_id)
                    
                    progress = int(((i + 1) / total_animals) * 100)
                    
                    data = {
                        'animal_id': animal_id,
                        'ibc_meuwissen': ibc_meuwissen,
                        'ibc_traditional': ibc_traditional,
                        'progress': progress
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                
                yield f"event: complete\ndata: {json.dumps({'message': 'A számítás befejeződött.'})}\n\n"

            except Exception as e:
                current_app.logger.error(f"Calculation error in stream: {e}", exc_info=True)
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
    df['ibc'] = df['animal_id'].apply(lambda id: calculator.get_inbreeding_meuwissen(id))

    # Standardize farm column
    if 'farm_id' in df.columns and 'farm' not in df.columns:
        df.rename(columns={'farm_id': 'farm'}, inplace=True)
    elif 'farm_id' not in df.columns and 'farm' not in df.columns:
        df['farm'] = 'Ismeretlen'

    # Ensure 'gender' column exists
    if 'gender' not in df.columns:
        dam_ids = df['dam_id'].dropna().unique()
        sire_ids = df['sire_id'].dropna().unique()
        df['gender'] = 'U'
        df.loc[df['animal_id'].isin(dam_ids), 'gender'] = 'F'
        df.loc[df['animal_id'].isin(sire_ids), 'gender'] = 'M'
    
    df['gender'] = df['gender'].astype(str).str.upper()

    columns_to_return = ['animal_id', 'farm', 'ibc']
    sires = df[df['gender'] == 'M'][columns_to_return].to_dict(orient='records')
    dams = df[df['gender'] == 'F'][columns_to_return].to_dict(orient='records')
    
    return jsonify({'sires': sires, 'dams': dams})


@main_blueprint.route('/pedigree/export_results', methods=['POST'])
def export_results():
    session_id = request.form.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return "Hiba: Érvénytelen vagy lejárt munkamenet.", 400

    try:
        df = current_app.sessions[session_id]['data'].copy()
        calculator = current_app.sessions[session_id]['calculator']

        if 'farm_id' in df.columns:
            df.rename(columns={'farm_id': 'farm'}, inplace=True)
        elif 'farm' not in df.columns:
            df['farm'] = 'Ismeretlen'

        sire_ids = [int(id) for id in request.form.get('sire_ids', '').split(',') if id]
        dam_ids = [int(id) for id in request.form.get('dam_ids', '').split(',') if id]

        sire_details = df[df['animal_id'].isin(sire_ids)].to_dict('records')
        dam_details = df[df['animal_id'].isin(dam_ids)].to_dict('records')

        export_data = []
        for sire in sire_details:
            sire_ibc = calculator.get_inbreeding_meuwissen(sire['animal_id'])
            for dam in dam_details:
                dam_ibc = calculator.get_inbreeding_meuwissen(dam['animal_id'])
                offspring_ibc = calculator.calculate_coancestry(sire['animal_id'], dam['animal_id'])
                export_data.append({
                    'Apa Azonosító': sire['animal_id'],
                    'Apa Tenyészet': sire['farm'],
                    'Apa BTE': sire_ibc,
                    'Anya Azonosító': dam['animal_id'],
                    'Anya Tenyészet': dam['farm'],
                    'Anya BTE': dam_ibc,
                    'Várható Utód BTE': offspring_ibc
                })
        
        output_df = pd.DataFrame(export_data)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            output_df.to_excel(writer, index=False, sheet_name='Párosítási Eredmények')
        output.seek(0)

        return send_file(
            output, 
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='szimulacios_eredmenyek.xlsx'
        )

    except Exception as e:
        current_app.logger.error(f"Error exporting results: {e}", exc_info=True)
        return "Hiba az exportálás során.", 500

@main_blueprint.route('/pedigree/simulation_results', methods=['POST'])
def simulation_results():
    session_id = request.form.get('session_id')
    if not session_id or session_id not in current_app.sessions:
        return "Hiba: Érvénytelen vagy lejárt munkamenet.", 400

    try:
        df = current_app.sessions[session_id]['data'].copy()
        calculator = current_app.sessions[session_id]['calculator']

        if 'farm_id' in df.columns:
            df.rename(columns={'farm_id': 'farm'}, inplace=True)
        elif 'farm' not in df.columns:
            df['farm'] = 'Ismeretlen'

        sire_ids = [int(id) for id in request.form.get('sire_ids', '').split(',') if id]
        dam_ids = [int(id) for id in request.form.get('dam_ids', '').split(',') if id]

        sire_details = df[df['animal_id'].isin(sire_ids)].to_dict('records')
        dam_details = df[df['animal_id'].isin(dam_ids)].to_dict('records')

        results_data = []
        for sire in sire_details:
            sire_ibc = calculator.get_inbreeding_meuwissen(sire['animal_id'])
            for dam in dam_details:
                dam_ibc = calculator.get_inbreeding_meuwissen(dam['animal_id'])
                offspring_ibc = calculator.calculate_coancestry(sire['animal_id'], dam['animal_id'])
                results_data.append({
                    'sire_id': sire['animal_id'],
                    'sire_farm': sire['farm'],
                    'sire_ibc': sire_ibc,
                    'dam_id': dam['animal_id'],
                    'dam_farm': dam['farm'],
                    'dam_ibc': dam_ibc,
                    'offspring_ibc': offspring_ibc
                })
        
        return render_template('pedigree/simulation_result.html', results=results_data)

    except Exception as e:
        current_app.logger.error(f"Error in simulation results: {e}", exc_info=True)
        return "Hiba a szimulációs eredmények generálása során.", 500
