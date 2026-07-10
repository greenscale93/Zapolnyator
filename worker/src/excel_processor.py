import os
import shutil
import logging
import tempfile
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import msoffcrypto
import re

logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def read_excel_structure(file_path: str) -> dict:
    try:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    file = msoffcrypto.OfficeFile(f)
                    if file.is_encrypted():
                        try:
                            file.load_key(password="987456")
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
                                file.decrypt(tmp)
                                tmp_path = tmp.name
                            wb = load_workbook(tmp_path, data_only=True)
                            os.unlink(tmp_path)
                        except:
                            return {"status": "error", "error_message": "Cannot decrypt file with default password"}
                    else:
                        wb = load_workbook(file_path, data_only=True)
            except:
                wb = load_workbook(file_path, data_only=True)
        else:
            return {"status": "error", "error_message": "File not found"}
        
        sheets = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            header_row = 2
            headers = [cell.value for cell in ws[header_row] if cell.value]
            sheets[sheet_name] = {
                "headers": headers,
                "rows_count": ws.max_row,
                "max_column": ws.max_column,
                "header_row": header_row
            }
        return {"status": "success", "result": {"sheets": sheets}}
    except Exception as e:
        logger.exception("read_excel_structure error")
        return {"status": "error", "error_message": str(e)}

def clean_number(value):
    """
    Очищает строку от неразрывных пробелов, пробелов-разделителей тысяч,
    заменяет запятую на точку и преобразует в число.
    Если преобразование не удаётся, возвращает исходное значение.
    """
    if isinstance(value, str):
        # Удаляем все пробелы (включая неразрывные) и другие нецифровые символы, кроме точки и запятой
        cleaned = re.sub(r'[^\d,.-]', '', value.replace('\u00a0', '').replace(' ', ''))
        # Заменяем запятую на точку (для десятичных)
        cleaned = cleaned.replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            return value
    return value

async def apply_sheet_mapping(source_path: str, template_path: str, sheet_name: str, mapping: dict, month: str, year: int, password: str = "987456", output_path: str = None) -> dict:
    try:
        # 1. Определяем файл для работы
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

        # 2. Читаем источник (Excel) в DataFrame
        df_source = pd.read_excel(source_path, header=0)
        logger.info(f"Source rows before filters: {len(df_source)}")

        # 3. Применяем общие фильтры
        filters = mapping.get("filters", {})
        exclude_filters = mapping.get("exclude_filters", {})

        if filters:
            for col, val in filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str) == str(val)]
                    logger.info(f"Applied filter {col} = {val}, rows left: {len(df_source)}")
                else:
                    logger.warning(f"Filter column '{col}' not found in source")
        if exclude_filters:
            for col, val in exclude_filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str) != str(val)]
                    logger.info(f"Applied exclude filter {col} != {val}, rows left: {len(df_source)}")
                else:
                    logger.warning(f"Exclude column '{col}' not found in source")

        if df_source.empty:
            return {"status": "error", "error_message": "No data after applying filters"}

        # 4. Применяем view_filters (если есть)
        view_filters = mapping.get("view_filters", {})
        if view_filters:
            for col, allowed_values in view_filters.items():
                if col in df_source.columns:
                    df_source = df_source[df_source[col].astype(str).isin([str(v) for v in allowed_values])]
                    logger.info(f"Applied view filter {col} in {allowed_values}, rows left: {len(df_source)}")
                else:
                    logger.warning(f"View filter column '{col}' not found in source")

        if df_source.empty:
            return {"status": "error", "error_message": "No data after applying view filters"}

        # 5. Группировка и агрегация
        group_by = mapping.get("group_by")
        aggregations = mapping.get("aggregations", {})

        if group_by:
            # Преобразуем group_by в список, если строка
            if isinstance(group_by, str):
                group_by = [group_by]
            # Проверяем, что все колонки есть
            group_by = [col for col in group_by if col in df_source.columns]
            if not group_by:
                logger.warning("No valid group_by columns, skipping grouping")
                data_for_insert = df_source.to_dict(orient='records')
            else:
                # Создаём агрегационные функции
                agg_funcs = {}
                for agg_col, agg_type in aggregations.items():
                    if agg_col in df_source.columns:
                        if agg_type == "sum":
                            agg_funcs[agg_col] = "sum"
                        elif agg_type == "concat":
                            agg_funcs[agg_col] = lambda x: "; ".join(x.dropna().astype(str).unique())
                        elif agg_type == "concat_premia":
                            # Специальная функция: собираем комментарии только из строк с "Премия"
                            def concat_premia(series):
                                # series — это группа, нужно получить комментарии из строк где ВидНачисления == "Премия"
                                # для этого нужно получить доступ к исходному DataFrame, но у нас только серия
                                # Мы можем использовать apply с доступом к группе
                                # В pandas groupby можно передать пользовательскую функцию, которая получает всю группу
                                return "dummy"
                            # Мы не можем использовать lambda, потому что нужен доступ к группе.
                            # Поэтому мы переделаем groupby через apply.
                            agg_funcs[agg_col] = None  # будет обработано отдельно
                        else:
                            agg_funcs[agg_col] = agg_type
                # Если есть concat_premia, используем apply с пользовательской функцией
                if "concat_premia" in aggregations.values():
                    def group_agg(group):
                        result = {}
                        # Для колонок group_by берём первое значение (они одинаковы)
                        for col in group_by:
                            result[col] = group[col].iloc[0]
                        # Суммируем Оклад и Премию
                        if 'Оклад' in df_source.columns:
                            result['Оклад'] = group[group['ВидНачисления'] == 'Оплата труда']['Оклад'].astype(float).sum()
                        else:
                            result['Оклад'] = 0
                        if 'Премия' in df_source.columns:
                            result['Премия'] = group['Премия'].astype(float).sum()
                        else:
                            result['Премия'] = 0
                        # Комментарий: только из строк с Премия
                        if 'Комментарий' in df_source.columns:
                            comments = group[group['ВидНачисления'] == 'Премия']['Комментарий'].dropna().astype(str).unique()
                            result['Комментарий'] = "; ".join(comments)
                        else:
                            result['Комментарий'] = ""
                        return pd.Series(result)
                    # Применяем группировку
                    df_grouped = df_source.groupby(group_by, as_index=False).apply(group_agg).reset_index(drop=True)
                    data_for_insert = df_grouped.to_dict(orient='records')
                else:
                    # Обычная группировка с sum/concat
                    # Для concat используем агрегацию с пользовательской функцией
                    agg_funcs_final = {}
                    for agg_col, agg_type in aggregations.items():
                        if agg_col in df_source.columns:
                            if agg_type == "sum":
                                agg_funcs_final[agg_col] = "sum"
                            elif agg_type == "concat":
                                agg_funcs_final[agg_col] = lambda x: "; ".join(x.dropna().astype(str).unique())
                            else:
                                agg_funcs_final[agg_col] = agg_type
                    if agg_funcs_final:
                        df_grouped = df_source.groupby(group_by, as_index=False).agg(agg_funcs_final)
                        # Переименовываем колонки обратно
                        # df_grouped уже имеет колонки group_by и agg_cols
                        data_for_insert = df_grouped.to_dict(orient='records')
                    else:
                        data_for_insert = df_source.to_dict(orient='records')
        else:
            data_for_insert = df_source.to_dict(orient='records')

        # 6. Открываем рабочую книгу
        wb = load_workbook(output_path)
        if sheet_name not in wb.sheetnames:
            return {"status": "error", "error_message": f"Sheet '{sheet_name}' not found in template"}
        ws = wb[sheet_name]

        header_row = mapping.get("header_row", 2)
        logger.info(f"Header row: {header_row}")

        # 7. Подготавливаем данные для вставки с учётом маппинга колонок
        source_cols = mapping.get("source_columns", {})
        source_cols = {int(k): v for k, v in source_cols.items()}
        append = mapping.get("append_to_end", True)

        rows_to_insert = []
        for row_dict in data_for_insert:
            new_row = {}
            for target_col_idx, source_expr in source_cols.items():
                if source_expr == "{month} {year}":
                    new_row[target_col_idx] = f"{month} {year}"
                else:
                    if source_expr in row_dict:
                        val = row_dict[source_expr]
                        if any(keyword in source_expr for keyword in ['Оклад', 'Премия', 'Сумма', 'Ставка', 'НДС']):
                            val = clean_number(val)
                        new_row[target_col_idx] = val
                    else:
                        new_row[target_col_idx] = None
            rows_to_insert.append(new_row)

        if not rows_to_insert:
            return {"status": "error", "error_message": "No data to insert"}

        logger.info(f"Prepared {len(rows_to_insert)} rows for insertion")

        # 8. Вставляем строки ПОСЛЕ последней существующей строки
        if append:
            last_row = ws.max_row
            while last_row > 0:
                row_has_data = False
                for col in range(1, ws.max_column + 1):
                    if ws.cell(row=last_row, column=col).value is not None:
                        row_has_data = True
                        break
                if row_has_data:
                    break
                last_row -= 1
            start_row = last_row + 1
            if start_row <= header_row:
                start_row = header_row + 1
        else:
            if ws.max_row > header_row:
                ws.delete_rows(header_row + 1, ws.max_row - header_row)
            start_row = header_row + 1

        logger.info(f"Start row: {start_row}, number of rows to insert: {len(rows_to_insert)}")

        for i, row_dict in enumerate(rows_to_insert, start=start_row):
            for col_idx, value in row_dict.items():
                if value is not None:
                    ws.cell(row=i, column=col_idx).value = value

        wb.save(output_path)
        logger.info(f"File saved: {output_path}")

        return {"status": "success", "output_path": output_path, "rows_added": len(rows_to_insert)}
    except Exception as e:
        logger.exception("apply_sheet_mapping error")
        return {"status": "error", "error_message": str(e)}