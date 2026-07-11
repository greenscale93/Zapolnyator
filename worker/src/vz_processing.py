"""
Предобработка данных для листа 'Взаиморасчеты'.

Содержит функцию _preprocess_vzaimoraschety, извлечённую из excel_processor.py
для уменьшения размера модуля.
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def preprocess_vzaimoraschety(
    df: pd.DataFrame,
    config: dict,
    office_mapping: dict = None
) -> pd.DataFrame:
    """
    Предобработка данных для листа 'Взаиморасчеты':
    - вычисление направления (из поля direction_field, по умолчанию 'Направление')
      Доход -> Исходящие, Расход -> Входящие
    - обработка спецофисов: строки с ключевым словом в ПодразделениеКонтрагентДляОтчета
      делятся по ТипОборота (БДР/БДДС) на "по актам" и "по ДС"
    - пустые ПодразделениеКонтрагентДляОтчета заполняются из office_mapping или спецофисной заменой
    - схлопывание дублей БДР/БДДС для строк, НЕ содержащих ключевое слово
    """
    direction_field = config.get("direction_field", "Направление")
    turnover_field = config.get("turnover_type_field", "ТипОборота")

    dir_map = config.get("direction_mapping", {})
    df["Направление"] = df[direction_field].map(dir_map)
    unmapped = df[df["Направление"].isna()][direction_field].unique()
    if len(unmapped) > 0:
        raise ValueError(
            f"Не удалось определить направление для значений {list(unmapped)} "
            f"в поле '{direction_field}'"
        )

    office_col = "ПодразделениеКонтрагентДляОтчета"
    keyword = config.get("special_office_keyword", "")
    replace_rules = config.get("special_office_replace", {})

    if turnover_field not in df.columns:
        raise ValueError(
            f"Для обработки Взаиморасчетов нужна колонка '{turnover_field}'"
        )
    if "ПодразделениеКонтрагент" not in df.columns:
        raise ValueError(
            "Для обработки Взаиморасчетов нужна колонка 'ПодразделениеКонтрагент'"
        )

    # 1. Заполненные спецофисы (содержат ключевое слово) – только валидация
    #    Замена на БДР/БДДС и префикс комментария делаются единым блоком
    #    на шаге 3 (после всех мэппингов), чтобы учесть и строки,
    #    получившие ключевое слово через office_mapping.
    mask_special_filled = df[office_col].astype(str).str.contains(keyword, na=False)
    if mask_special_filled.any():
        missing_turnover = df.loc[mask_special_filled, turnover_field].isna()
        if missing_turnover.any():
            raise ValueError(
                f"Для спецофиса не указан {turnover_field}"
            )

    # 2. Пустые office_col – заполняем из словаря маппинга или заменой по ТипОборота
    mask_empty = df[office_col].isna() | (df[office_col].astype(str).str.strip() == "")
    if mask_empty.any():
        sub_office_col = "ПодразделениеКонтрагент"
        if office_mapping is None:
            office_mapping = {}
        for idx in df[mask_empty].index:
            sub = df.loc[idx, sub_office_col]
            if pd.isna(sub) or str(sub).strip() == "":
                raise ValueError(f"Пустой ПодразделениеКонтрагент в строке {idx}")
            sub_str = str(sub).strip()
            mapped = office_mapping.get(sub_str)
            if mapped:
                df.loc[idx, office_col] = mapped
            else:
                # fallback: используем спецофисную замену по ТипОборота (БДР/БДДС)
                fallback = replace_rules.get(df.loc[idx, turnover_field], "Неизвестно")
                df.loc[idx, office_col] = fallback
                logger.warning(
                    f"Не найден маппинг для '{sub_str}', использован fallback {fallback}"
                )

    # ---- Замена ключевого слова на БДР/БДДС + префикс комментария ----
    # Применяется ко ВСЕМ строкам, где office_col содержит ключевое слово,
    # независимо от того, было оно изначально или пришло через мэппинг.
    mask_keyword = df[office_col].astype(str).str.contains(keyword, na=False)
    if mask_keyword.any():
        df.loc[mask_keyword, office_col] = (
            df.loc[mask_keyword, turnover_field].map(replace_rules)
        )
        still_na = df.loc[mask_keyword, office_col].isna()
        if still_na.any():
            bad_vals = df.loc[mask_keyword & still_na, turnover_field].unique()
            raise ValueError(
                f"Для спецофиса не задана замена для {turnover_field}: {list(bad_vals)}"
            )

        # Комментарий: префикс "<ПодразделениеКонтрагент>: "
        sub_office_col = "ПодразделениеКонтрагент"
        for idx in df[mask_keyword].index:
            office_name = (
                str(df.loc[idx, sub_office_col]).strip()
                if pd.notna(df.loc[idx, sub_office_col]) else ""
            )
            orig_comment = (
                str(df.loc[idx, "Комментарий"]).strip()
                if pd.notna(df.loc[idx, "Комментарий"]) else ""
            )
            if office_name:
                df.loc[idx, "Комментарий"] = (
                    f"{office_name}: {orig_comment}" if orig_comment else office_name
                )
            else:
                df.loc[idx, "Комментарий"] = orig_comment

    # 3. Схлопывание для обычных офисов (не содержащих keyword)
    is_special = df[office_col].astype(str).str.contains(keyword, na=False)
    df_special = df[is_special].copy()
    df_regular = df[~is_special].copy()

    if not df_regular.empty:
        group_keys = [
            "Подразделение", "Контрагент", "Проект", office_col, "Направление"
        ]
        df_regular = df_regular.groupby(group_keys, as_index=False).first()
        for col in [turnover_field, "ПодразделениеКонтрагент"]:
            if col in df_regular.columns:
                df_regular.drop(columns=[col], inplace=True)

    df = pd.concat([df_regular, df_special], ignore_index=True)

    cols_to_drop = [
        c for c in [turnover_field, "ПодразделениеКонтрагент"]
        if c in df.columns
    ]
    if direction_field != "Направление" and direction_field in df.columns:
        cols_to_drop.append(direction_field)
    if cols_to_drop:
        df.drop(columns=cols_to_drop, inplace=True)

    return df
