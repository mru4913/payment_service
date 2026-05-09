#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
SQLAlchemy基础模型类
所有ORM模型都应继承自此基类
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    SQLAlchemy DeclarativeBase 的基类。
    所有ORM模型都应继承自此基类。
    """

    pass
