"""
Утилиты для работы с взаиморасчетами (ВЗ).

Извлечено из main.py для уменьшения размера модуля.
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def get_empty_vz_contractors(source_path: str) -> list:
    """
    Читает Excel-файл и возвращает список контрагентов-подразделений,
    у которых в строках Взаиморасчет (Доход/Расход) пустое поле
    ПодразделениеКонтрагентДляОтчета.
    """
    df = pd.read_excel(source_path, header=0, engine='calamine')
    # Фильтр: только строки Взаиморасчет и направления Доход/Расход
    mask = (
        df["ТипЗаписи"].astype(str) == "Взаиморасчет"
    ) & (
        df["Направление"].astype(str).isin(["Доход", "Расход"])
    )
    df_vz = df[mask]
    # Пустые ПодразделениеКонтрагентДляОтчета
    empty_mask = (
        df_vz["ПодразделениеКонтрагентДляОтчета"].isna()
        | (df_vz["ПодразделениеКонтрагентДляОтчета"].astype(str).str.strip() == "")
    )
    contractors = (
        df_vz.loc[empty_mask, "ПодразделениеКонтрагент"]
        .dropna()
        .unique()
        .tolist()
    )
    return contractors
