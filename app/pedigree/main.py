import os
import json
import datetime
from flask import Blueprint, render_template, request, redirect, url_for
import pandas as pd
from werkzeug.utils import secure_filename
from .validation.validator import validate_pedigree
from .analysis.analyzer import calculate_inbreeding_tabular, calculate_inbreeding_path_based

bp = Blueprint('pedigree', __name__, url_prefix='/pedigree')

UPLOAD_FOLDER = 'tmp/uploads'
LOG_FILE = os.path.join(UPLOAD_FOLDER, 'upload.log')

def log_message(message):
    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(f"{datetime.datetime.now()}: {message}\n")
    except Exception:
        pass

@bp.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'GET':
        return render_template('upload.html')

    log_message("--- NEW UPLOAD ATTEMPT ---")
    pedigree_file = request.files.get('pedigree_file')

    if not pedigree_file or not pedigree_file.filename:
        log_message("Upload check FAILED: No file selected or file has no name.")
        return render_template('upload.html', errors=['Nincs fájl kiválasztva. Kérjük, válasszon egy CSV fájlt.'])

    log_message(f"File details: name='{pedigree_file.name}', filename='{pedigree_file.filename}'")

    try:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(pedigree_file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        log_message(f"Saving file to: {filepath}")
        pedigree_file.save(filepath)
        log_message("File save SUCCESSFUL.")

        log_message(f"Issuing redirect to 'pedigree.view' with filename: {filename}")
        return redirect(url_for('pedigree.view', filename=filename))

    except Exception as e:
        log_message(f"CRITICAL ERROR during upload: {e}")
        return render_template('upload.html', errors=[f"Váratlan hiba történt: {e}"])

@bp.route('/view')
def view():
    log_message("Request received for 'view' page.")
    filename = request.args.get('filename')
    errors = request.args.getlist('errors') 

    if not filename:
        log_message("'view' page check FAILED: No filename in query parameter.")
        return redirect(url_for('pedigree.upload'))

    filepath = os.path.join(UPLOAD_FOLDER, filename)

    if not os.path.exists(filepath):
        log_message(f"'view' page check FAILED: File does not exist. Path checked: {filepath}")
        return redirect(url_for('pedigree.upload'))
    
    log_message(f"Reading CSV from: {filepath}")
    df = pd.read_csv(filepath, comment='#')
    log_message("CSV read successfully. Rendering 'view_pedigree.html'")
    
    df_html = df.to_html(classes='pedigree-table', index=False, na_rep='-', border=0)

    return render_template('view_pedigree.html', data=df_html, errors=errors, filename=filename)

@bp.route('/analysis')
def analysis():
    log_message("Request received for 'analysis' page.")
    filename = request.args.get('filename')

    if not filename:
        log_message("'analysis' page check FAILED: No filename in query parameter.")
        return redirect(url_for('pedigree.upload'))

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        log_message(f"'analysis' page check FAILED: File does not exist. Path checked: {filepath}")
        return redirect(url_for('pedigree.upload'))

    log_message("Reading CSV for analysis.")
    df = pd.read_csv(filepath, comment='#')
    
    log_message("Starting validation...")
    errors = validate_pedigree(df)
    if errors:
        log_message(f"Validation FAILED with errors: {errors}")
        return redirect(url_for('pedigree.view', filename=filename, errors=errors))

    log_message("Validation PASSED. Starting inbreeding calculations.")
    
    core_df = df[['animal_id', 'sire_id', 'dam_id']]

    inbreeding_tabular = calculate_inbreeding_tabular(core_df.copy())
    inbreeding_path = calculate_inbreeding_path_based(core_df.copy())
    
    df_tabular = pd.DataFrame(list(inbreeding_tabular.items()), columns=['animal_id', 'IBC (Táblázatos)'])
    df_path = pd.DataFrame(list(inbreeding_path.items()), columns=['animal_id', 'IBC (Ösvénykereső)'])
    
    df_merged = pd.merge(df_tabular, df_path, on='animal_id')
    df_merged.rename(columns={'animal_id': 'Állat Azonosító'}, inplace=True)
    df_merged = df_merged.sort_values('Állat Azonosító').reset_index(drop=True)
    
    log_message("Analysis COMPLETE.")

    return render_template(
        'analysis.html', 
        filename=filename, 
        analysis_data=df_merged.to_html(
            classes=['result-table'], 
            index=False,
            float_format='{:.4f}'.format
        )
    )

@bp.route('/mating-selection')
def mating_selection():
    filename = request.args.get('filename')
    if not filename:
        return redirect(url_for('pedigree.upload'))

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        return redirect(url_for('pedigree.upload'))

    df = pd.read_csv(filepath)
    
    core_df = df[['animal_id', 'sire_id', 'dam_id']]
    inbreeding_tabular = calculate_inbreeding_tabular(core_df.copy())
    ibc_df = pd.DataFrame(list(inbreeding_tabular.items()), columns=['animal_id', 'ibc'])
    
    df = pd.merge(df, ibc_df, on='animal_id', how='left')
    df['ibc'] = df['ibc'].fillna(0)

    farms = sorted([farm for farm in df['farm_id'].unique() if pd.notna(farm)])
    
    animals_df = df[pd.notna(df['farm_id']) & pd.notna(df['gender'])].copy()
    animals_json = animals_df[['animal_id', 'farm_id', 'gender', 'ibc']].to_json(orient='records')

    return render_template(
        'mating_selection.html',
        filename=filename,
        farms=farms,
        animals_json=animals_json
    )

@bp.route('/run-simulation', methods=['POST'])
def run_simulation():
    filename = request.args.get('filename')
    if not filename:
        return redirect(url_for('pedigree.upload'))

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        return redirect(url_for('pedigree.upload'))

    try:
        df = pd.read_csv(filepath)
        # --- Get base IBCs for all animals --- #
        core_df = df[['animal_id', 'sire_id', 'dam_id']]
        base_ibcs = calculate_inbreeding_tabular(core_df.copy())
        ibc_df = pd.DataFrame(list(base_ibcs.items()), columns=['animal_id', 'ibc'])
        df = pd.merge(df, ibc_df, on='animal_id', how='left')
        df['ibc'] = df['ibc'].fillna(0)

        selected_dams_ids = [int(i) for i in request.form.getlist('selected_dams')]
        selected_sires_ids = [int(i) for i in request.form.getlist('selected_sires')]

        if not selected_sires_ids or not selected_dams_ids:
            return render_template('simulation_result.html', simulation_data=[], filename=filename)

        hypothetical_offspring = []
        mating_pairs = []
        offspring_id_counter = -1

        for sire_id in selected_sires_ids:
            for dam_id in selected_dams_ids:
                mating_pairs.append({'sire_id': sire_id, 'dam_id': dam_id, 'offspring_id': offspring_id_counter})
                hypothetical_offspring.append({'animal_id': offspring_id_counter, 'sire_id': sire_id, 'dam_id': dam_id})
                offspring_id_counter -= 1

        offspring_df = pd.DataFrame(hypothetical_offspring)
        extended_df = pd.concat([core_df, offspring_df], ignore_index=True)
        
        all_ibcs = calculate_inbreeding_tabular(extended_df)

        sire_details = df[df['animal_id'].isin(selected_sires_ids)].set_index('animal_id').to_dict('index')
        dam_details = df[df['animal_id'].isin(selected_dams_ids)].set_index('animal_id').to_dict('index')

        results_by_sire = {
            sire_id: {
                'sire_id': sire_id,
                'sire_ibc': sire_details.get(sire_id, {}).get('ibc', 0),
                'tenyeszet': sire_details.get(sire_id, {}).get('farm_id'),
                'total_ibc': 0,
                'details': []
            } for sire_id in selected_sires_ids
        }

        for pair in mating_pairs:
            sire_id = pair['sire_id']
            dam_id = pair['dam_id']
            offspring_id = pair['offspring_id']
            offspring_ibc = all_ibcs.get(offspring_id, 0)
            
            results_by_sire[sire_id]['total_ibc'] += offspring_ibc
            results_by_sire[sire_id]['details'].append({
                'dam_id': dam_id,
                'dam_ibc': dam_details.get(dam_id, {}).get('ibc', 0),
                'dam_tenyeszet': dam_details.get(dam_id, {}).get('farm_id'),
                'offspring_ibc': offspring_ibc
            })

        final_results = sorted(results_by_sire.values(), key=lambda x: x['total_ibc'])

        return render_template('simulation_result.html', simulation_data=final_results, filename=filename)

    except Exception as e:
        log_message(f"Error in run_simulation: {e}")
        return f"An error occurred: {e}"
