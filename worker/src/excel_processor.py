"""
Обработка Excel: чтение структуры, запись данных в шаблон.

Все операции записи — через LibreOffice UNO (lo_client).
Чтение — через python-calamine.
"""
import os
import shutil
import logging
import tempfile
import re
import pandas as pd
import msoffcrypto

from src.vz_processing import preprocess_vzaimoraschety
from src.lo_client import lo_client
from src.template_reader import _open_sheet

logger = logging.getLogger(__name__)


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========


async def read_excel_structure(file_path: str) -> dict:
    """Читает структуру листов Excel-файла."""
    try:
        if not os.path.exists(file_path):
            return {"status": "error", "error_message": "File not found"}

        # Расшифровка если нужно
        real_path = file_path
        tmp = None
        try:
            with open(file_path, 'rb') as f:
                office_file = msoffcrypto.OfficeFile(f)
                if office_file.is_encrypted():
                    office_file.load_key(password="987456")
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                    office_file.decrypt(tmp)
                    tmp.close()
                    real_path = tmp.name
        except Exception:
            pass

        try:
            from python_calamine import CalamineWorkbook
            wb = CalamineWorkbook.from_path(real_path)
            sheets = {}
            for name in wb.sheet_names:
                data = wb.get_sheet_by_name(name).to_python()
                headers = []
                if len(data) > 1:
                    headers = [str(h) for h in data[1] if h is not None]
                sheets[name] = {
                    "headers": headers,
                    "rows_count": len(data),
                    "max_column": len(data[0]) if data else 0,
                    "header_row": 2
                }
            return {"status": "success", "result": {"sheets": sheets}}
        finally:
            if tmp and real_path != file_path:
                try:
                    os.unlink(real_path)
                except Exception:
                    pass
    except Exception as e:
        logger.exception("read_excel_structure error")
        return {"status": "error", "error_message": str(e)}


def clean_number(value):
    """Очищает число от неразрывных пробелов и прочего мусора."""
    if isinstance(value, str):
        cleaned = re.sub(r'[^\d,.-]', '', value.replace('\u00a0', '').replace(' ', ''))
        cleaned = cleaned.replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            return value
    return value


# Алиас для обратной совместимости
_preprocess_vzaimoraschety = preprocess_vzaimoraschety


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========


async def apply_sheet_mapping(
    source_path: str,
    template_path: str,
    sheet_name: str,
    mapping: dict,
    month: str,
    year: int,
    password: str = "987456",
    output_path: str = None
) -> dict:
    try:
        if output_path is None:
            output_dir = os.path.dirname(template_path)
            output_filename = f"ДКП_10_-_{month}_{year}.xlsx"
            output_path = os.path.join(output_dir, output_filename)
            shutil.copy2(template_path, output_path)
            logger.info(f"Created new output file: {output_path}")

            if password:
                try:
                    with open(output_path, 'rb') as f:
                        file = msoffcrypto.OfficeFile(f)
                        if file.is_encrypted():
                            file.load_key(password=password)
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                                file.decrypt(tmp)
                                tmp_path = tmp.name
                            shutil.move(tmp_path, output_path)
                            logger.info("File decrypted")
                except Exception as e:
                    logger.warning(f"Decrypt failed: {e}")
        else:
            if not os.path.exists(output_path):
                return {"status": "error", "error_message": f"Output file not found: {output_path}"}
            logger.info(f"Using existing output file: {output_path}")

        # ======== ЧТЕНИЕ И ОЧИСТКА ========
        df_source = pd.read_excel(source_path, header=0, engine='calamine')
        logger.info(f"Source rows before filters: {len(df_source)}")

        money_keywords = ['Оклад', 'Премия', 'Сумма', 'Ставка', 'НДС']
        for col in df_source.columns:
            if col == "СтавкаНДС":
                continue
            if any(kw in col for kw in money_keywords):
                df_source[col] = (
                    df_source[col]
                    .astype(str)
                    .str.replace(r'[\s\u00a0]', '', regex=True)
                    .str.replace(',', '.')
                )
                df_source[col] = pd.to_numeric(df_source[col], errors='coerce')

        # ======== ФИЛЬТРЫ ========
        filters = mapping.get("filters", {})
        exclude_filters = mapping.get("exclude_filters", {})

        if exclude_filters:
            for col, val in exclude_filters.items():
                if col in df_source.columns:
                    if isinstance(val, list):
                        df_source = df_source[~df_source[col].astype(str).isin([str(v) for v in val])]
                    else:
                        df_source = df_source[df_source[col].astype(str) != str(val)]
                    logger.info(f"Applied exclude filter {col}, rows left: {len(df_source)}")

        if filters:
            for col, val in filters.items():
                if col in df_source.columns:
                    if isinstance(val, list):
                        df_source = df_source[df_source[col].astype(str).isin([str(v) for v in val])]
                    else:
                        df_source = df_source[df_source[col].astype(str) == str(val)]
                    logger.info(f"Applied filter {col}, rows left: {len(df_source)}")

        if df_source.empty:
            return {"status": "error", "error_message": "No data after applying filters"}

        # ======== КАСТОМНАЯ ОБРАБОТКА (ВЗАИМОРАСЧЕТЫ) ========
        custom = mapping.get("custom_processing")
        if custom and custom.get("type") == "vzaimoraschety":
            office_mapping = custom.get("office_mapping", {})
            df_source = preprocess_vzaimoraschety(df_source, custom, office_mapping)

        if df_source.empty:
            return {"status": "error", "error_message": "No data after custom processing"}

        # ======== VIEW FILTERS ========
        view_filters = mapping.get("view_filters", {})
        if view_filters:
            for col, allowed_values in view_filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str).isin([str(v) for v in allowed_values])]
                    logger.info(f"Applied view filter {col}, rows left: {len(df_source)}")
            if df_source.empty:
                return {"status": "error", "error_message": "No data after view filters"}

        # ======== ГРУППИРОВКА И АГРЕГАЦИЯ ========
        group_by = mapping.get("group_by")
        aggregations = mapping.get("aggregations", {})

        if group_by:
            if isinstance(group_by, str):
                group_by = [group_by]
            group_by = [col for col in group_by if col in df_source.columns]
            if not group_by:
                data_for_insert = df_source.to_dict(orient='records')
            else:
                if "concat_premia" in aggregations.values():
                    def group_agg(group):
                        result = {}
                        for col in group_by:
                            result[col] = group[col].iloc[0]
                        result['Оклад'] = group.loc[group.get('ВидНачисленияЗП') == 'Оплата труда', 'Оклад'].sum() if 'Оклад' in df_source.columns else 0
                        result['Премия'] = group['Премия'].sum() if 'Премия' in df_source.columns else 0
                        if 'Комментарий' in df_source.columns:
                            comments = group.loc[group.get('ВидНачисленияЗП') == 'Премия', 'Комментарий'].dropna().astype(str).unique()
                            result['Комментарий'] = "; ".join(comments)
                        else:
                            result['Комментарий'] = ""
                        return pd.Series(result)
                    df_grouped = df_source.groupby(group_by, as_index=False).apply(group_agg).reset_index(drop=True)
                    data_for_insert = df_grouped.to_dict(orient='records')
                else:
                    agg_funcs = {}
                    for agg_col, agg_type in aggregations.items():
                        if agg_col in df_source.columns:
                            if agg_type == "sum":
                                agg_funcs[agg_col] = "sum"
                            elif agg_type == "concat":
                                agg_funcs[agg_col] = lambda x: "; ".join(x.dropna().astype(str).unique())
                            else:
                                agg_funcs[agg_col] = agg_type
                    if agg_funcs:
                        df_grouped = df_source.groupby(group_by, as_index=False).agg(agg_funcs)
                        data_for_insert = df_grouped.to_dict(orient='records')
                    else:
                        data_for_insert = df_source.to_dict(orient='records')
        else:
            data_for_insert = df_source.to_dict(orient='records')

        # ======== ПОДГОТОВКА ДАННЫХ ДЛЯ ВСТАВКИ ========
        source_cols = mapping.get("source_columns", {})
        source_cols = {int(k): v for k, v in source_cols.items()}

        rows_to_insert = []
        for row_dict in data_for_insert:
            new_row = {}
            for target_col_idx, source_expr in source_cols.items():
                if source_expr == "{month} {year}":
                    # Период всегда как текст — "Май 2026"
                    new_row[target_col_idx] = f"{month} {year}"
                else:
                    if source_expr in row_dict:
                        val = row_dict[source_expr]
                        if any(kw in source_expr for kw in ['Оклад', 'Премия', 'Сумма', 'Ставка', 'НДС']) and source_expr != "СтавкаНДС":
                            val = clean_number(val)
                        new_row[target_col_idx] = val
                    else:
                        new_row[target_col_idx] = None
            rows_to_insert.append(new_row)

        if not rows_to_insert:
            return {"status": "error", "error_message": "No data to insert"}

        logger.info(f"Prepared {len(rows_to_insert)} rows for insertion")

        # ======== ВСТАВКА ЧЕРЕЗ LIBREOFFICE ========
        if lo_client is None:
            return {"status": "error", "error_message": "LibreOffice UNO not available"}

        doc = await lo_client.open_document(output_path, password=None)
        try:
            sheet = await lo_client.get_sheet(doc, sheet_name)
            header_row = mapping.get("header_row", 2)

            # Конвертируем target_col_idx из 1-based в 0-based
            rows_0based = []
            for row_dict in rows_to_insert:
                r = {}
                for col_idx, value in row_dict.items():
                    r[col_idx - 1] = value
                rows_0based.append(r)

            # Находим последнюю строку и добавляем после неё
            start_row = await lo_client.find_last_row(sheet)
            if start_row < header_row:
                start_row = header_row

            start_row = start_row + 1  # строка ПОСЛЕ последней заполненной
            await lo_client.append_rows(sheet, rows_0based, start_row=start_row)

            await lo_client.save_document(doc, output_path)
            logger.info(f"File saved via LibreOffice: {output_path}")

            return {"status": "success", "output_path": output_path, "rows_added": len(rows_to_insert)}
        finally:
            await lo_client.close_document(doc)

    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}