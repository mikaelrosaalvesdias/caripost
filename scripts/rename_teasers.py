#!/usr/bin/env python3
"""
Script para renomear teasers existentes com base no vídeo queimado de origem.
O novo nome segue o padrão: teaser_<run_id_prefix>_<timestamp>.mp4
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import get_conn, get_run


def sanitize_filename(name: str) -> str:
    """Remove caracteres inválidos de nomes de arquivo."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = name.replace(' ', '_')
    name = name[:100]
    return name


def get_run_wizard_state(run_id: str) -> dict:
    """Retorna o wizard_state de um run."""
    run = get_run(run_id)
    if not run:
        return {}
    try:
        request_json = json.loads(run['request_json']) if isinstance(run['request_json'], str) else (run['request_json'] or {})
    except:
        return {}
    return request_json.get('wizard_state') or {}


def get_teaser_info_from_runs():
    """Coleta informações de todos os teasers e seus vídeos de origem."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, request_json FROM runs").fetchall()
    
    teasers = []
    for row in rows:
        run_id = str(row['id'])
        try:
            request_json = json.loads(row['request_json']) if isinstance(row['request_json'], str) else (row['request_json'] or {})
        except:
            continue
        
        wizard_state = request_json.get('wizard_state') or {}
        teaser_key = wizard_state.get('teaser_object_key')
        
        if not teaser_key:
            continue
        
        burned_key = wizard_state.get('teaser_source_object_key') or wizard_state.get('burned_object_key')
        
        teasers.append({
            'run_id': run_id,
            'run_id_prefix': run_id[:8],
            'teaser_object_key': teaser_key,
            'burned_object_key': burned_key,
        })
    
    return teasers


def extract_burned_name(burned_key: str) -> str:
    """Extrai um nome legível do caminho do vídeo queimado."""
    if not burned_key:
        return ''
    
    parts = burned_key.split('/')
    if parts:
        filename = parts[-1]
        if filename.endswith('.mp4'):
            filename = filename[:-4]
        return filename
    return ''


def generate_teaser_filename(run_id: str, burned_key: str = None) -> str:
    """Gera um nome de arquivo para o teaser baseado no vídeo queimado."""
    run_prefix = run_id[:8]
    
    if burned_key:
        burned_name = extract_burned_name(burned_key)
        if burned_name:
            return f"teaser_{run_prefix}_{burned_name}.mp4"
    
    return f"teaser_{run_prefix}.mp4"


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Renomear teasers com base no vídeo queimado')
    parser.add_argument('--dry-run', action='store_true', help='Apenas mostra o que seria feito')
    parser.add_argument('--verbose', '-v', action='store_true', help='Mostra detalhes')
    args = parser.parse_args()
    
    print("Coletando informações dos teasers...")
    teasers = get_teaser_info_from_runs()
    
    if not teasers:
        print("Nenhum teaser encontrado.")
        return
    
    print(f"Encontrados {len(teasers)} teasers.")
    
    from app.main import _rename_media_ref, _media_ref_exists, _s3_client
    
    renamed = 0
    errors = 0
    skipped = 0
    
    for teaser in teasers:
        run_id = teaser['run_id']
        run_prefix = teaser['run_id_prefix']
        teaser_key = teaser['teaser_object_key']
        burned_key = teaser['burned_object_key']
        
        new_filename = generate_teaser_filename(run_id, burned_key)
        
        if args.verbose:
            print(f"\nRun: {run_id}")
            print(f"  Teaser atual: {teaser_key}")
            print(f"  Vídeo queimado: {burned_key}")
            print(f"  Novo nome: {new_filename}")
        
        if args.dry_run:
            print(f"  [DRY-RUN] Seria renomear para: {new_filename}")
            continue
        
        if not _media_ref_exists(media_ref=teaser_key):
            print(f"  [SKIP] Teaser não encontrado: {teaser_key}")
            skipped += 1
            continue
        
        try:
            result = _rename_media_ref(media_ref=teaser_key, new_filename=new_filename, s3=_s3_client())
            new_key = result.get('object_key')
            print(f"  [OK] Renomeado: {teaser_key} -> {new_key}")
            renamed += 1
        except FileExistsError:
            print(f"  [SKIP] Já existe: {new_filename}")
            skipped += 1
        except FileNotFoundError:
            print(f"  [SKIP] Não encontrado: {teaser_key}")
            skipped += 1
        except Exception as e:
            print(f"  [ERROR] {teaser_key}: {e}")
            errors += 1
    
    print(f"\nResumo: {renamed} renomeados, {skipped} pulados, {errors} erros")
    
    if args.dry_run:
        print("\n[DRY-RUN] Nenhuma alteração foi feita.")


if __name__ == '__main__':
    main()
