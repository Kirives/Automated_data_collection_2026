from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Record(BaseModel):
    model_config=ConfigDict(extra='ignore',allow_inf_nan=False)
    business_key: str=Field(min_length=8,max_length=100)
    source: Literal['books','worldbank']
    kind: Literal['book','population']
    source_id: str=Field(min_length=3,max_length=40)
    title: str=Field(min_length=2,max_length=600)
    value: Decimal=Field(gt=0,le=Decimal('2000000000'),max_digits=14,decimal_places=2)
    unit: Literal['GBP','persons']
    stock: int|None=Field(default=None,ge=0,le=100000)
    rating: int|None=Field(default=None,ge=1,le=5)
    category: str|None=None
    year: int|None=Field(default=None,ge=1960,le=2100)
    country_code: str|None=None
    source_url: str
    collected_at: datetime
    parser_version: str=Field(min_length=3)
    status: int=Field(ge=200,le=299)

    @field_validator('title')
    @classmethod
    def meaningful_title(cls,value):
        if not value.strip() or not any(c.isalpha() for c in value):
            raise ValueError('Название должно содержать буквы')
        return value

    @field_validator('source_url')
    @classmethod
    def valid_source_url(cls,value):
        parts=urlsplit(value)
        if parts.scheme!='https' or parts.hostname not in {'books.toscrape.com','api.worldbank.org'}:
            raise ValueError('Нужен HTTPS URL одного из двух источников')
        return value

    @field_validator('collected_at')
    @classmethod
    def aware_utc(cls,value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Дата должна содержать часовой пояс')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def coherent_record(self):
        if self.kind=='book':
            if self.source!='books' or self.unit!='GBP' or self.stock is None or self.rating is None:
                raise ValueError('Книга: источник books, GBP, остаток и рейтинг обязательны')
            if not re.fullmatch(r'[0-9a-f]{16}',self.source_id):
                raise ValueError('UPC должен состоять из 16 шестнадцатеричных символов')
            if self.value>Decimal('10000'):raise ValueError('Цена учебной книги не выше 10000 GBP')
            expected='books:'+self.source_id
        else:
            if self.source!='worldbank' or self.unit!='persons' or self.year is None:
                raise ValueError('Население: источник worldbank, persons и год обязательны')
            if not re.fullmatch(r'[A-Z]{3}',self.country_code or ''):
                raise ValueError('Нужен трёхбуквенный код страны')
            if self.value!=self.value.to_integral_value():raise ValueError('Население должно быть целым')
            if self.stock is not None or self.rating is not None:
                raise ValueError('Остаток и рейтинг к населению не применяются')
            expected=f'worldbank:{self.country_code}:SP.POP.TOTL:{self.year}'
        if self.business_key!=expected:raise ValueError('Бизнес-ключ не согласован с источником')
        return self
