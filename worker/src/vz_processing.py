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

    # 1. Заполненные спецофисы (содержат ключевое слово) – разделяем по БДР/БДДС
    mask_special_filled = df[office_col].astype(str).str.contains(keyword, na=False)
    if mask_special_filled.any():
        df.loc[mask_special_filled, office_col] = (
            df.loc[mask_special_filled, turnover_field].map(replace_rules)
        )
        still_na = df.loc[mask_special_filled, office_col].isna()
        if still_na.any():
            bad_vals = df.loc[mask_special_filled & still_na, turnover_field].unique()
            raise ValueError(
                f"Для спецофиса не задана замена для {turnover_field}: {list(bad_vals)}"
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
