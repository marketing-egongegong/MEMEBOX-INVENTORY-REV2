# -*- coding: utf-8 -*-
"""
Inventory Control — Amazon + TikTok Shop
Single-file Streamlit app. Deploy on Railway with ONLY: app.py + requirements.txt

Env vars (no hardcoding):
  GOOGLE_SHEET_ID               Amazon source spreadsheet id
  GOOGLE_SERVICE_ACCOUNT_JSON   service account key (raw JSON or base64)

Railway start command (Settings -> Deploy -> Custom Start Command):
  streamlit run app.py --server.port $PORT --server.address 0.0.0.0
(If Railway runs `python app.py` directly, this file self-launches streamlit.)
"""

import os
import sys


def _under_streamlit():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


# If executed as a plain python process (not via `streamlit run`), relaunch under streamlit.
if __name__ == "__main__" and not _under_streamlit():
    import subprocess
    _port = os.environ.get("PORT", "8501")
    sys.exit(subprocess.call([
        sys.executable, "-m", "streamlit", "run", os.path.abspath(__file__),
        "--server.port", _port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]))

# ----------------------------------------------------------------------------
import base64
import io
import json
import random
import re
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ============================ CONFIG ============================
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
SA_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

STATUS_CRIT, STATUS_WARN = 30, 60
PO_THRESHOLD, PO_TARGET_DAYS = 45, 90
TR_FBA_DAYS, TR_TARGET_DAYS = 30, 60
REFRESH_TTL = 300  # 5 min

COLORS = {"crit": "#F87171", "warn": "#FBBF24", "heal": "#34D399",
          "amz": "#FF9900", "tt": "#FE2C55", "accent": "#2DD4BF"}

FBA_SUBCOLS = ["FBA_Available", "FBA_inbound_working", "FBA_inbound_shipped",
               "FBA_inbound_receiving", "FBA_reserved_orders",
               "FBA_reserved_transfer", "FBA_reserved_processing"]

FBA_MATCH = {
    "FBA_Available": ["afn-fulfillable-quantity", "fulfillable", "available", "afnfulfillable", "fba available"],
    "FBA_inbound_working": ["afn-inbound-working-quantity", "inbound working", "inboundworking", "working"],
    "FBA_inbound_shipped": ["afn-inbound-shipped-quantity", "inbound shipped", "inboundshipped", "shipped"],
    "FBA_inbound_receiving": ["afn-inbound-receiving-quantity", "inbound receiving", "inboundreceiving", "receiving"],
    "FBA_reserved_orders": ["reserved-customerorders", "reserved customer", "reserved orders", "customerorders"],
    "FBA_reserved_transfer": ["reserved-fc-transfers", "reserved transfer", "fc-transfers", "fctransfers"],
    "FBA_reserved_processing": ["reserved-fc-processing", "reserved processing", "fc-processing", "fcprocessing"],
}

COL = {
    "sku": ["sku", "sap", "sapcode", "sap code", "seller sku", "seller-sku", "msku", "item", "품번", "상품코드", "코드"],
    "asin": ["asin", "child asin", "child-asin", "childasin"],
    "name": ["product name", "productname", "제품명", "상품명", "name", "title", "product"],
    "brand": ["brand name", "brand", "브랜드"],
    "price": ["price", "unit price", "단가", "discount price"],
    "qty": ["available", "fulfillable", "quantity", "qty", "units", "unit", "재고", "재고수량", "수량", "stock", "onhand", "가용재고"],
    "s7": ["units shipped t7", "7 day", "7day", "7d", "last 7", "7일", "t7"],
    "s30": ["units shipped t30", "30 day", "30day", "30d", "last 30", "30일", "t30"],
    "date": ["date", "날짜", "일자", "order date", "purchase-date", "주문일"],
    "units": ["units", "unit", "quantity", "qty", "수량", "판매량", "units sold", "sold", "quantity ordered"],
    "revenue": ["revenue", "amount", "sales amount", "매출", "금액", "ordered product sales", "item-price"],
}

# Embedded product master (SKU / ASIN / Brand / Name) — seed so the app works before the sheet is wired.
SEED_CSV = r"""담당자,Account Name,Brand Name,제품명,SKU,Child ASIN,Discount Price,Prime Day
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SMUDGE BRUSH,32002123,B09BTLFZ7Q,$7.20,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI SNOWFLAKE WHIPPING CLEANSER,32001103,B0F7XTHK5X,$10.20,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI MARSHMALLOW WHIP MAKER,32001119,B06XHH3GLF,$5.60,Best Deal
이유빈,MBX Corp,NOONI,NOONI PORE CLEANSING DUAL BRUSH,32001145,B072LWM8VY,$14.40,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI APPLEBUTTER LIP MASK,32001264,B07CP3B241,$15.30,Best Deal
이유빈,MBX Corp,I'M MEME,I'M MEME Eyeshadow I'm Stick Shadow Shimmer 001 Sugar Bling,32001420,B0948QBSM8,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME Eyeshadow I'm Stick Shadow Shimmer 003 Pink Charm,32001422,B08R6RCDB3,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M STICK SHADOW SHIMMER 004 ROSE CAPE,32001423,B0D6XT2G7N,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M STICK SHADOW SHIMMER 005 TAUPE TRINKET,32001424,B0D6XT2G7N,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK SHADING 001 BRONZER,32001472,B0D3H8YPKM,$12.75,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK HIGHLIGHTER 001 CHAMPAGNE GOLD,32001473,B0D3H8YPKM,$12.75,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 001 ROSE,32001474,B0D6DYJPPZ,$12.75,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 001 ROSE,32001474_s,B08593F3JP,$7.50,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 002 CORAL,32001475,B0D6DYJPPZ,$12.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 002 CORAL,32001475_S,B085943Z92,$12.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA BLUSHER PALETTE,32001637,B0DPGQX6WJ,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME PEP BALM 001 RECHARGER,32001701,B08C9JQCST,$11.20,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME PEP BALM 002 OH-OH,32001702,B08C9JQCST,$11.20,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME PEP BALM 004 CORNER,32001704,B08C9JQCST,$9.35,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA BLUSHER PALETTE FRUIT FLAVOR,32001763,B0DPGQX6WJ,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M OIL CUT PACT 001 SKIN MATTIFYING,32001854,B0BZTMGBRH,$14.78,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME PINK BLUR TONE-UP PACT,32001990,B0BZTMGBRH,$20.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME COLOR KEY RING WATER GEL TINT 01 CORAL PICNIC,32002022,B0BCF5XLGN,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME COLOR KEY RING WATER GEL TINT 02 ORANGE DELIGHT,32002023,B0BCF5XLGN,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME COLOR KEY RING WATER GEL TINT 06 MY CHERRY,32002027,B0BCF5XLGN,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA CONTOUR PALETTE ROASTING COFFEE,32002091,B0DPGQL3RY,$17.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA CONTOUR PALETTE FROZEN CHOCO,32002092,B0DPGQL3RY,$17.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME WONDER SOFT LAYER EYE PALETTE 01 MY TEDDY,32003406,B0CPRB3BST,$24.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME WONDER SOFT LAYER EYE PALETTE 02 MY BUNNY,32003407,B0CPRB3BST,$24.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK SHADING 002 COOL BRONZER,32003448,B0D3H8YPKM,$12.75,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME SKIN FIT TONE-UP PACT,32003458,B0BZTMGBRH,$14.02,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME MULTI CUBE 07 DEEP CHOCOLATE MOUSSE,32003514,B08KPVLTTN,$20.80,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 003 BLURRY NUDE,32003520,B0D6DYJPPZ,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 004 MELLOW PINK,32003521,B0D6DYJPPZ,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK BLUSHER 005 BLISS MAUVE,32003522,B0D6DYJPPZ,$9.60,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI APPLEBERRY LIP MASK,32003523,B0CZ33PV8T,$15.30,Best Deal
이유빈,MBX Corp,NOONI,NOONI SNOW AQUA 0 LHA TONING CLEANSING OIL,32003551,B0DDPDKGBW,$16.80,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI SNOW AQUA 0 RICE CERAMIDE BARRIER CARE CLEANSING OIL,32003813,B0FNW7QSN7,$16.80,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI SNOWFLAKE WHIPPING CLEANSER 2EA,63007603,B0F7XTHK5X,$20.00,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI MUCH NEEDED FACIAL CLEANSING KIT,63008043,B0DYNHYLMH,$11.19,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI SNOW AQUA 0 LHA TONING CLEANSING OIL 2EA,63008485,B0DDPDKGBW,$28.00,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI DOUBLE CLEANSING GIFT DUO,63008498,B0FNW7QSN7,$27.19,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME PURPLE COTTON TONE CONTROL PACT,32002222_s,B0BZTMGBRH,$20.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK DUAL_001 CONTOURING_V2 5g,32003359,B09FJQF88V,$14.40,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI DAILY TURNOVER PEEL PAD,32003321,B0DLDXGB86,$20.80,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M MULTI STICK DUAL 002 COOL CONTOURING,32003361,B0D3H8YPKM,$11.91,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SILHOUETTE GLOSS TINT 07 CHIC BURGUNDY,32003251,B0BYZ5X9KQ,$15.30,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SILHOUETTE GLOSS TINT 08 MAXIMAL RED,32003252,B0BYZ5X9KQ,$15.30,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SILHOUETTE GLOSS TINT 04 NEO SCARLET,32003248,B0BYZ5X9KQ,$15.30,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SILHOUETTE MATTE VELVET TINT 01 RETRO PEACH,32003290,B0BYZ5X9KQ,$15.30,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME SKIN PILLOW SETTING POWDER,32003259,B0BZTMGBRH,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA BLUSHER PALETTE BLOSSOM TEA BLENDED,32003313,B0DPGQX6WJ,$16.00,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME LIP SILHOUETTE MATTE VELVET TINT 09 READY TO COOL,32003298,B0BYZ5X9KQ,$15.30,Prime Exclusive Discounts
이유빈,MBX Corp,NOONI,NOONI DAILY TURNOVER PEEL PAD (7 COUNT),32003363,B0DLDXGB86,$4.40,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME I'M AFTERNOON TEA BLUSHER PALETTE MILK TEA TIME,32002252,B0DPGQX6WJ,$17.60,Prime Exclusive Discounts
이유빈,MBX Corp,I'M MEME,I'M MEME COLOR KEY RING VELVET TINT 03 BAKED BRICK,32002303,B0BCF5XLGN,$16.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE LET'S GET SHEET FACED,32001129,B071FPLRGS,$19.30,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE WHITE CAT HEADBAND,32001142,B07G45ZBK3,$8.49,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE BROWN BEAR HEADBAND,32001143_s,B072Q223K2,$8.49,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE SILICONE MASK BRUSH,32001144,B0DP1XP43K,$8.00,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA CAT NAP 01 PEACH,32001350,B086VPNHYG,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DON'T SETTLE 01 SWEET RICE,32001351,B086PMX7TH,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DON'T SETTLE 02 BANANA MILK,32001352,B086PMX7TH,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DON'T SETTLE 03 MOONCAKE,32001353,B086PMX7TH,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DON'T SETTLE 04 WAFFLES,32001354,B086PMX7TH,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DON'T SETTLE 05 FORTUNE COOKIE,32001355,B086PMX7TH,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 01 ROSEWATER,32001363,B0B7KYV7BD,$7.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 02 ORANGE BLOSSOM,32001364,B0B7KYV7BD,$16.62,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA CHEEKY STAMP 01 COY,32001384,B086SM61R4,$9.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 03 TOASTED CARAMEL,32001393,B0B7KYV7BD,$9.99,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE CAKE MY DAY,32001528,B0DPY4917V,$20.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE MATCHA MOOD,32001529 - stickerless,B07MJT6YYP,$17.50,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE MINI SCOOPS,32001532,B07XQK9VNM,$16.00,Best Deal
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 07 GLOWING GUAVA,32001595,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 08 CHOCOLATE DAHLIA,32001596,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE PLUSH PARTY,32001607,B0BZVLYGH1,$12.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GLOW EASY,32001612,B0CCNR1TT8,$9.60,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA WINK STAMP,32001630,B0DNNPW3VF,$23.20,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE YOGA KITTEN,32001670,B07XTRM6QK,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE JUICY KITTEN,32001671,B07XTSFF1N,$20.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE NAMASTE KITTEN,32001681,B07XTQMW1Z,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GLOW KEY,32001781,B0861DSC5T,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 10 SPIKED GINGER,32001810,B0B7KYV7BD,$18.99,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE KITTEN MY BALANCE ON,32001866,B0DNYK8THN,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BALMY BENTO 01 PINA COLADA,32001871,B08Z27JXKW,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE PAWFECT FACE SCRUBBER,32001913,B08JRTP35Y,$8.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE SPACE KITTEN,32001926,B0DTNZS7HV,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE SUGAR KITTEN,32001928,B0DTNZS7HV,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE CHILL KITTEN,32001934,B08Q7QTJDR,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA GLOSS SHOT 01 CRYSTAL CLEAR,32001937,B0BXCRKBBS,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA GLOSS SHOT 02 MILK TEA,32001938,B0BXCRKBBS,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA GLOSS SHOT 03 HONEY DRIZZLE,32001939,B0BXCRKBBS,$15.20,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GET THE SCOOP,32001944,B0DP1XP43K,$8.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE TWEEZE THE DAY,32001945-new,B0DNWT88BH,$8.00,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA PLAY BENTO 01 BUTTER UP,32001946,B08Y63VQHJ,$24.00,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA PLAY BENTO 02 CLOUD LATTE,32001947,B08Y63VQHJ,$24.00,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA PLAY BENTO 03 MOCHAMALLOW,32001948,B08Y63VQHJ,$23.20,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE BRIGHT SIDE UP,32002032,B0DPH1RFWP,$21.60,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE SAY YOU DEW,32002033,B0B7VVYCJW,$20.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE VITAMIN TO-GLOW PACK,32002034,B08WLS6BR3,$21.60,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 13 VELVET DREAM,32002045,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 14 NEUTRAL MOMENT,32002046,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA WINK LASH TRIO,32002102,B097S8KXKZ,$24.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE SCOOP PARTY,32002162,B0DYRT4SJ1,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA LOVE SWIPE 01 CALL ME,32002188,B09TN9MS8F,$13.66,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA WINK STAMP LONG,32002223,B0DNNPW3VF,$23.20,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 16 PEACH MADELINE,32002244,B0B7KYV7BD,$19.12,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 17 MAUVE BOUQUET,32002245,B0B7KYV7BD,$20.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE READY AIM CLEAR,32002250,B0B14V5JSB,$20.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE TIMEOUT BLEMISH PATCH ORIGINAL,32002281,B0DKLMFLMN,$12.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE TIMEOUT BLEMISH PATCH PLUS,32002282,B0DKLMFLMN,$12.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE TIMEOUT BLEMISH PATCH DARK SPOT,32002283,B0DKLMFLMN,$12.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE ROLLING WITH IT,32002291,B0DFXRCSQV,$9.60,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE FIX MY ZIT ACNE GEL TREATMENT,32003234,B0CCT36HPY,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE PROPER POPPER,32003236,B0BF9MBH5N,$8.00,Best Deal
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 01 CHERRY SPRITZ,32003238,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 02 SQUEEZE GUAVA,32003239,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 03 BERRY COLADA,32003240,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 04 FIG SODA,32003241,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 05 PEACH FIZZ,32003242,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JELLY CHARM 06 MOCHA GLAZE,32003243,B0BT4F65P8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA PLAY BENTO 2.5 DOLCE CAPPUCCINO,32003261,B08Y63VQHJ,$24.00,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 18 CORAL SUNRISE,32003306,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA BEAUTY BENTO 19 FOREST NIGHT,32003307,B0B7KYV7BD,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE HOW DOUGH I LOOK,32003325,B0DYRT4SJ1,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JUICY GLASS LIP OIL 01 ROSE HIP SPRITZ,32003341,B0CG553ZP8,$11.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JUICY GLASS LIP OIL 02 RASPBERRY REFRESHER,32003342,B0CG553ZP8,$11.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JUICY GLASS LIP OIL 03 APRICOT ALLURE,32003343,B0CG553ZP8,$11.99,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE COOKIE O' GLOW,32003372,B0DPY4917V,$17.50,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE MEET BUBBLE KITTY,32003373,B0DP3JJPT2,$9.60,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GLOW EASY POMEGRANATE VITAMIN C LIP OIL,32003383,B0CCNR1TT8,$12.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GLOW EASY RASPBERRY VITAMIN C LIP OIL,32003384,B0CCNR1TT8,$12.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE CUSHY CRUSH SUGAR VITAMIN C LIP SCRUB,32003386,B0CKV4Z5DL,$12.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE TWINKLE STAR HEADBAND,32003394,B07G45ZBK3,$8.50,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE STARRY KITTEN NIGHT,32003395,B0CHXLMJVC,$24.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE PANDA HEADBAND,32003420,B07G45ZBK3,$8.50,Best Deal
김석현,MBX Corp,I DEW CARE,I DEW CARE HYDRA VIBES 3-HYALURONIC ACID CLEANSER,32003424,B0CV7F9C6P,$12.80,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE HYDRA VIBES 10-HYALURONIC ACID SERUM,32003425,B0DPH1RFWP,$16.00,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE HYDRA VIBES 8-HYALURONIC ACID MOISTURIZER,32003426,B0CV7JL7RC,$14.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA WINK DAZZLE ICE ILLUSION,32003437,B0CVR9W7CD,$16.71,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA WINK DAZZLE CHAMPAGNE SEQUIN,32003438,B0CVR9W7CD,$17.59,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE GREEN COSMETIC BAG,32003450,B0CNNXFHLR,$6.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DEWY BAR BERRY SPARKLER,32003459,B0CZ3LP7C8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA DEWY BAR STRAWBERRY SORBET,32003460,B0CZ3LP7C8,$19.99,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA LOVE BLUR LIP BALM PURE CUPID,32003496,B0D3QJRHYN,$14.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA LOVE BLUR LIP BALM SWEET BESTIE,32003497,B0D3QJRHYN,$14.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE AQUA KITTEN,32003685,B0DP1VYWKG,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE ASTRO KITTEN,32003686,B0DP1RJBM4,$22.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA JUICY GLASS LIP BALM WATERMELON COOLER,32003741,B0FLJ31CNH,$14.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE DEW NOT DISTURB,32003749,B0FKBC4KPG,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,I DEW CARE,I DEW CARE RESTING BLISS FACE,32003750,B0FKBC4KPG,$18.40,Prime Exclusive Discounts
김석현,MBX Corp,KAJA,KAJA HEART & SEOUL BEST OF KAJA SET,Kaja_HeartandSeoul,B0FGKMQ6BG,$36.00,Prime Exclusive Discounts"""


# ============================ HELPERS ============================
def norm(s):
    return re.sub(r"[\s_\-./]+", "", str("" if s is None else s).strip().lower())


def numv(v):
    if v is None:
        return 0.0
    m = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(m) if m not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def clean_sku(v):
    s = str("" if v is None else v).strip()
    s = re.sub(r"\s*-\s*stickerless$", "", s, flags=re.I)
    s = re.sub(r"_s(tickerless)?$", "", s, flags=re.I)
    s = re.sub(r"(_new|_temp|-new)$", "", s, flags=re.I)
    return s


def fmt(n):
    try:
        return f"{round(float(n)):,}"
    except (ValueError, TypeError):
        return "0"


def usd(n):
    try:
        return "$" + f"{round(float(n)):,}"
    except (ValueError, TypeError):
        return "$0"


def pick(df, cands):
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    ncols = {c: norm(c) for c in cols}
    for cand in cands:
        nc = norm(cand)
        for c in cols:
            if ncols[c] == nc:
                return c
    for cand in cands:
        nc = norm(cand)
        for c in cols:
            if nc and nc in ncols[c]:
                return c
    return None


def status_of(cov):
    if cov is None or cov != cov:  # NaN
        return "Healthy"
    if cov >= 999:
        return "Healthy"
    if cov < STATUS_CRIT:
        return "Critical"
    if cov <= STATUS_WARN:
        return "Warning"
    return "Healthy"


def date_key(d):
    return pd.to_datetime(d).strftime("%Y-%m-%d")


# ============================ MASTER ============================
@st.cache_data(show_spinner=False)
def load_master_from_csv(csv_text):
    df = pd.read_csv(io.StringIO(csv_text))
    return _master_from_df(df)


def _master_from_df(df):
    ks, kn = pick(df, COL["sku"]), pick(df, COL["name"])
    ka, kb, kp = pick(df, COL["asin"]), pick(df, COL["brand"]), pick(df, COL["price"])
    rows = []
    for _, r in df.iterrows():
        if not ks:
            continue
        raw = str(r[ks]).strip()
        if not raw or raw.lower() == "nan":
            continue
        sku = clean_sku(raw)
        rows.append({
            "SKU": sku,
            "ASIN": str(r[ka]).strip() if ka else "",
            "Product Name": str(r[kn]).strip() if kn else sku,
            "Brand": str(r[kb]).strip() if kb else "",
            "price": numv(r[kp]) if kp else 0.0,
        })
    m = pd.DataFrame(rows).drop_duplicates(subset=["SKU"], keep="first")
    return m.reset_index(drop=True)


# ============================ GOOGLE SHEETS ============================
def _credentials():
    if not SA_JSON:
        return None, "GOOGLE_SERVICE_ACCOUNT_JSON 미설정"
    try:
        txt = SA_JSON if SA_JSON.startswith("{") else base64.b64decode(SA_JSON).decode("utf-8")
        info = json.loads(txt)
    except Exception as e:  # noqa: BLE001
        return None, f"서비스 계정 JSON 파싱 실패: {e}"
    try:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        return creds, None
    except Exception as e:  # noqa: BLE001
        return None, f"자격 증명 생성 실패: {e}"


def _values_to_df(values):
    if not values:
        return pd.DataFrame()
    header = [str(h).strip() for h in values[0]]
    width = len(header)
    body = []
    for row in values[1:]:
        row = list(row) + [""] * (width - len(row))
        body.append(row[:width])
    return pd.DataFrame(body, columns=header)


@st.cache_data(ttl=REFRESH_TTL, show_spinner=False)
def read_sheet(sheet_id, sa_json_key):
    """Returns dict: configured, error, cconma, fba, sales, master (DataFrames)."""
    out = {"configured": False, "error": None,
           "cconma": pd.DataFrame(), "fba": pd.DataFrame(),
           "sales": pd.DataFrame(), "master": pd.DataFrame(), "detected": {}}
    if not sheet_id:
        out["error"] = "GOOGLE_SHEET_ID 미설정"
        return out
    creds, err = _credentials()
    if err:
        out["error"] = err
        return out
    try:
        from googleapiclient.discovery import build
        svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]

        def has(t, *keys):
            tn = norm(t)
            return any(norm(k) in tn for k in keys)

        role = {}
        for t in titles:
            if "cconma" not in role and has(t, "cconma"):
                role["cconma"] = t
            elif "fba" not in role and has(t, "fba"):
                role["fba"] = t
            elif "sales" not in role and (has(t, "일별") or has(t, "saleshist") or has(t, "dailysales")):
                role["sales"] = t
            elif "master" not in role and (has(t, "productinfo") or has(t, "master") or has(t, "마스터")):
                role["master"] = t
        out["detected"] = role
        if role:
            resp = svc.spreadsheets().values().batchGet(
                spreadsheetId=sheet_id,
                ranges=[f"'{t}'" for t in role.values()],
                valueRenderOption="UNFORMATTED_VALUE").execute()
            ranges = resp.get("valueRanges", [])
            for i, key in enumerate(role.keys()):
                vals = ranges[i].get("values", []) if i < len(ranges) else []
                out[key] = _values_to_df(vals)
        out["configured"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = f"시트 읽기 실패: {e}"
    return out


# ============================ INDEX SOURCES ============================
def index_inv(df):
    """sku -> qty"""
    res = {}
    if df is None or df.empty:
        return res
    ks, kq = pick(df, COL["sku"]), pick(df, COL["qty"])
    if not ks:
        return res
    for _, r in df.iterrows():
        sku = clean_sku(r[ks])
        if not sku:
            continue
        res[sku] = res.get(sku, 0.0) + (numv(r[kq]) if kq else 0.0)
    return res


def index_fba(df):
    """sku -> {sub-col: qty}"""
    res = {}
    if df is None or df.empty:
        return res
    ks = pick(df, COL["sku"])
    if not ks:
        return res
    found = {k: pick(df, v) for k, v in FBA_MATCH.items()}
    for _, r in df.iterrows():
        sku = clean_sku(r[ks])
        if not sku:
            continue
        d = res.setdefault(sku, {c: 0.0 for c in FBA_SUBCOLS})
        for sub, col in found.items():
            if col:
                d[sub] += numv(r[col])
    return res


def index_sales(df):
    """sku -> {'s7','s30','daily': {date: {'u','rev'}}}"""
    res = {}
    if df is None or df.empty:
        return res
    ks = pick(df, COL["sku"])
    kdate = pick(df, COL["date"])
    ku = pick(df, COL["units"])
    krev = pick(df, COL["revenue"])
    k7, k30 = pick(df, COL["s7"]), pick(df, COL["s30"])
    if ks and (k7 or k30) and not kdate:
        for _, r in df.iterrows():
            sku = clean_sku(r[ks])
            if not sku:
                continue
            o = res.setdefault(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
            if k7:
                o["s7"] += numv(r[k7])
            if k30:
                o["s30"] += numv(r[k30])
        return res
    if ks and kdate:
        now = datetime.now()
        for _, r in df.iterrows():
            sku = clean_sku(r[ks])
            try:
                dt = pd.to_datetime(r[kdate])
            except Exception:  # noqa: BLE001
                continue
            if pd.isna(dt):
                continue
            u = numv(r[ku]) if ku else 1.0
            rev = numv(r[krev]) if krev else 0.0
            age = (now - dt.to_pydatetime()).days
            o = res.setdefault(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
            if age <= 7:
                o["s7"] += u
            if age <= 30:
                o["s30"] += u
            dk = dt.strftime("%Y-%m-%d")
            cell = o["daily"].setdefault(dk, {"u": 0.0, "rev": 0.0})
            cell["u"] += u
            cell["rev"] += rev
        return res
    return res


# ============================ DEMO ============================
def gen_demo(master):
    now = datetime.now()
    cc, fba, asales, tsales, tfbt = {}, {}, {}, {}, {}
    for i, p in master.iterrows():
        rnd = random.Random(1000 + i * 97 + len(p["SKU"]))
        velo = max(0, round(rnd.random() * rnd.random() * 26))
        tvelo = max(0, round(rnd.random() * rnd.random() * 14))
        cov_t = 8 + int(rnd.random() * 120)
        avail = max(0, round(velo * cov_t * (0.5 + rnd.random() * 0.8)))
        fba[p["SKU"]] = {
            "FBA_Available": avail,
            "FBA_inbound_working": round(velo * rnd.random() * 8),
            "FBA_inbound_shipped": round(velo * rnd.random() * 10),
            "FBA_inbound_receiving": round(velo * rnd.random() * 6),
            "FBA_reserved_orders": round(velo * rnd.random() * 4),
            "FBA_reserved_transfer": round(velo * rnd.random() * 3),
            "FBA_reserved_processing": round(velo * rnd.random() * 2),
        }
        cc[p["SKU"]] = round(velo * (5 + rnd.random() * 60))
        tfbt[p["SKU"]] = round(tvelo * (5 + rnd.random() * 40))
        a = {"s7": 0.0, "s30": 0.0, "daily": {}}
        t = {"s7": 0.0, "s30": 0.0, "daily": {}}
        price = p["price"] or 12
        for d in range(29, -1, -1):
            dt = now - timedelta(days=d)
            wk = 1.25 if dt.weekday() >= 5 else 1.0
            u = max(0, round(velo * wk * (0.5 + rnd.random())))
            tu = max(0, round(tvelo * wk * (0.5 + rnd.random())))
            a["s30"] += u
            t["s30"] += tu
            if d < 7:
                a["s7"] += u
                t["s7"] += tu
            dk = dt.strftime("%Y-%m-%d")
            a["daily"][dk] = {"u": u, "rev": u * price}
            t["daily"][dk] = {"u": tu, "rev": tu * price}
        asales[p["SKU"]] = a
        tsales[p["SKU"]] = t
    return {"cc": cc, "fba": fba, "asales": asales, "tsales": tsales, "tfbt": tfbt}


# ============================ COMPUTE ============================
def build_dataframes(master, cc_map, fba_map, asales, tcc_map, tfbt_map, tsales):
    amazon_rows, tiktok_rows, po_rows, tr_rows = [], [], [], []
    for _, p in master.iterrows():
        sku = p["SKU"]
        cc = cc_map.get(sku, 0.0)
        fb = fba_map.get(sku, {c: 0.0 for c in FBA_SUBCOLS})
        fba_total = sum(fb.get(c, 0.0) for c in FBA_SUBCOLS)
        sp = asales.get(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
        s7, s30 = sp["s7"], sp["s30"]
        da = s30 / 30.0
        total = cc + fba_total
        cov = (total / da) if da > 0 else (999 if total > 0 else 0)
        fba_cov = (fba_total / da) if da > 0 else (999 if fba_total > 0 else 0)
        st_ = status_of(cov)
        if cc or fba_total or s30 or s7:
            row = {"SKU": sku, "ASIN": p["ASIN"], "Product Name": p["Product Name"],
                   "Brand": p["Brand"], "CCONMA": cc}
            for c in FBA_SUBCOLS:
                row[c] = fb.get(c, 0.0)
            row.update({"FBA_Total": fba_total, "Total": total,
                        "7D": s7, "30D": s30, "DailyAvg": round(da, 2),
                        "CoverageDays": round(cov) if cov < 999 else 999, "Status": st_})
            amazon_rows.append(row)
            if cov < PO_THRESHOLD:
                rec = max(0, round(da * PO_TARGET_DAYS - total))
                cov_after = round((total + rec) / da) if da > 0 else 999
                po_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                "Current Inventory": total, "DailyAvg": round(da, 2),
                                "CoverageDays": round(cov) if cov < 999 else 999,
                                "Recommended Order Qty": rec, "발주 후 회전일": cov_after})
            if fba_cov < TR_FBA_DAYS and cc > 0:
                rec = max(0, min(cc, round(da * TR_TARGET_DAYS - fba_total)))
                if rec > 0:
                    tr_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                    "FBA Inventory": fba_total, "CCONMA Inventory": cc,
                                    "Recommended Transfer Qty": rec})
        # TikTok
        tcc = tcc_map.get(sku, 0.0)
        tfbt = tfbt_map.get(sku, 0.0)
        tsp = tsales.get(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
        t7, t30 = tsp["s7"], tsp["s30"]
        tda = t30 / 30.0
        ttotal = tcc + tfbt
        tcov = (ttotal / tda) if tda > 0 else (999 if ttotal > 0 else 0)
        if tcc or tfbt or t30 or t7:
            tiktok_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                "CCONMA": tcc, "FBT": tfbt, "Total": ttotal,
                                "7D": t7, "30D": t30, "DailyAvg": round(tda, 2),
                                "CoverageDays": round(tcov) if tcov < 999 else 999, "Status": status_of(tcov)})
    amazon = pd.DataFrame(amazon_rows)
    tiktok = pd.DataFrame(tiktok_rows)
    po = pd.DataFrame(po_rows)
    tr = pd.DataFrame(tr_rows)
    if not amazon.empty:
        amazon = amazon.sort_values("CoverageDays").reset_index(drop=True)
    if not tiktok.empty:
        tiktok = tiktok.sort_values("CoverageDays").reset_index(drop=True)
    if not po.empty:
        po = po.sort_values("CoverageDays").reset_index(drop=True)
    if not tr.empty:
        tr = tr.sort_values("Recommended Transfer Qty", ascending=False).reset_index(drop=True)
    return amazon, tiktok, po, tr


def sales_aggregate(master, sales, brand, names_filter=None):
    """Aggregate KPIs/series for the (brand-filtered) sales dict."""
    bybrand = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    daily = {}
    for sku, o in sales.items():
        if brand and bybrand.get(sku, "") != brand:
            continue
        for dk, cell in o.get("daily", {}).items():
            d = daily.setdefault(dk, {"u": 0.0, "rev": 0.0})
            d["u"] += cell["u"]
            d["rev"] += cell["rev"]
    entries = sorted(daily.items())
    today = datetime.now().strftime("%Y-%m-%d")
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    this_m = datetime.now().strftime("%Y-%m")
    prev_m = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    def g(k, f):
        return daily.get(k, {}).get(f, 0.0)

    def last(n, f):
        return sum(v[f] for _, v in entries[-n:])

    r_month = sum(v["rev"] for k, v in daily.items() if k[:7] == this_m)
    r_prev = sum(v["rev"] for k, v in daily.items() if k[:7] == prev_m)
    return {
        "entries": entries,
        "u_today": g(today, "u"), "u_7": last(7, "u"), "u_30": last(30, "u"),
        "r_today": g(today, "rev"), "r_yest": g(yest, "rev"),
        "r_7": last(7, "rev"), "r_30": last(30, "rev"),
        "r_month": r_month, "r_prev_month": r_prev,
    }


def sku_revenue_table(master, sales, brand):
    bybrand = {r["SKU"]: (r["Brand"], r["Product Name"]) for _, r in master.iterrows()}
    rows = []
    for sku, o in sales.items():
        b, nm = bybrand.get(sku, ("", sku))
        if brand and b != brand:
            continue
        rev = sum(c["rev"] for c in o.get("daily", {}).values())
        units = sum(c["u"] for c in o.get("daily", {}).values())
        if rev or units:
            rows.append({"SKU": sku, "Product Name": nm, "Brand": b,
                         "30D Units": round(units), "30D Revenue": round(rev)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("30D Revenue", ascending=False).reset_index(drop=True)
    return df


def brand_revenue(master, sales):
    bybrand = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    agg = {}
    for sku, o in sales.items():
        b = bybrand.get(sku, "")
        if not b:
            continue
        rev = sum(c["rev"] for c in o.get("daily", {}).values())
        agg[b] = agg.get(b, 0.0) + rev
    df = pd.DataFrame([{"Brand": k, "Revenue": round(v)} for k, v in agg.items()])
    if not df.empty:
        df = df.sort_values("Revenue", ascending=False).reset_index(drop=True)
    return df


def keyword_revenue(master, sales, brand_kw, name_kw):
    """Sum 30D revenue for SKUs whose brand+name match the keywords."""
    total = 0.0
    info = {r["SKU"]: (r["Brand"], r["Product Name"]) for _, r in master.iterrows()}
    for sku, o in sales.items():
        b, nm = info.get(sku, ("", ""))
        if brand_kw.lower() in b.lower() and name_kw.lower() in nm.lower():
            total += sum(c["rev"] for c in o.get("daily", {}).values())
    return total


# ============================ DATA ORCHESTRATION ============================
def get_state():
    sheet = read_sheet(SHEET_ID, SA_JSON[:24])  # key by prefix to keep cache stable
    # master: sheet PRODUCT INFO -> else seed
    if not sheet["master"].empty:
        master = _master_from_df(sheet["master"])
    else:
        master = load_master_from_csv(SEED_CSV)

    demo_on = st.session_state.get("demo", True)
    demo = gen_demo(master) if demo_on else None

    # uploads from session
    up_fbt = st.session_state.get("up_fbt")
    up_tsales = st.session_state.get("up_tsales")

    # CCONMA (shared warehouse tab) — used by BOTH Amazon and TikTok
    cc_map = index_inv(sheet["cconma"]) if not sheet["cconma"].empty else (demo["cc"] if demo else {})
    # Amazon FBA sub-columns
    fba_map = index_fba(sheet["fba"]) if not sheet["fba"].empty else (demo["fba"] if demo else {})
    # Amazon sales
    asales = index_sales(sheet["sales"]) if not sheet["sales"].empty else (demo["asales"] if demo else {})

    # TikTok CCONMA = same CCONMA tab; FBT + sales from upload (else demo)
    tcc_map = cc_map
    tfbt_map = index_inv(up_fbt) if up_fbt is not None else (demo["tfbt"] if demo else {})
    tsales = index_sales(up_tsales) if up_tsales is not None else (demo["tsales"] if demo else {})

    amazon, tiktok, po, tr = build_dataframes(master, cc_map, fba_map, asales, tcc_map, tfbt_map, tsales)
    return {"sheet": sheet, "master": master, "amazon": amazon, "tiktok": tiktok,
            "po": po, "tr": tr, "asales": asales, "tsales": tsales}


def apply_filters(df, brand, query, use_status=False):
    if df is None or df.empty:
        return df
    out = df
    if brand:
        out = out[out["Brand"] == brand]
    if query:
        q = query.strip().lower()
        cols = [c for c in ["SKU", "ASIN", "Product Name"] if c in out.columns]
        mask = False
        for c in cols:
            mask = mask | out[c].astype(str).str.lower().str.contains(q, na=False)
        out = out[mask]
    if use_status:
        fs = st.session_state.get("f_status", "전체")
        fc = st.session_state.get("f_cov", "전체")
        if fs != "전체" and "Status" in out.columns:
            out = out[out["Status"] == fs]
        if fc != "전체" and "CoverageDays" in out.columns:
            if fc == "< 30일":
                out = out[out["CoverageDays"] < 30]
            elif fc == "30–60일":
                out = out[(out["CoverageDays"] >= 30) & (out["CoverageDays"] <= 60)]
            elif fc == "> 60일":
                out = out[out["CoverageDays"] > 60]
    return out.reset_index(drop=True)


# ============================ UI HELPERS ============================
def style_status(df):
    if df is None or df.empty:
        return df
    sty = df.style
    if "Status" in df.columns:
        def color(v):
            c = {"Critical": COLORS["crit"], "Warning": COLORS["warn"], "Healthy": COLORS["heal"]}.get(v, "")
            return f"color:{c};font-weight:700" if c else ""
        sty = sty.map(color, subset=["Status"])
    return sty


def daily_line(entries, title, color):
    if not entries:
        st.info("일별 데이터 없음")
        return
    df = pd.DataFrame([{"date": k, "units": v["u"], "revenue": v["rev"]} for k, v in entries])
    fig = px.area(df, x="date", y="units", title=title)
    fig.update_traces(line_color=color, fillcolor=color.replace(")", ", 0.15)").replace("rgb", "rgba") if color.startswith("rgb") else color)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)


def hbar(df, x, y, title, color):
    if df is None or df.empty:
        st.info("데이터 없음")
        return
    fig = px.bar(df, x=x, y=y, orientation="h", title=title)
    fig.update_traces(marker_color=color)
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis=dict(autorange="reversed"),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)


def download_btn(df, label, name):
    if df is None or df.empty:
        return
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, csv, file_name=name, mime="text/csv")


# ============================ PAGES ============================
def page_home(S, brand):
    st.title("Home Dashboard")
    sheet = S["sheet"]
    src = "Google Sheet 연동" if sheet["configured"] else ("데모 데이터" if st.session_state.get("demo", True) else "업로드 데이터")
    st.caption(f"Amazon + TikTok Shop 재고 관제 · {src}")
    amz = apply_filters(S["amazon"], brand, "")
    po = apply_filters(S["po"], brand, "")
    tr = apply_filters(S["tr"], brand, "")
    crit = int((amz["Status"] == "Critical").sum()) if not amz.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("활성 SKU", fmt(len(amz)), brand or "전체 브랜드")
    c2.metric("Critical", crit, "Coverage < 30일")
    c3.metric("발주 필요", len(po) if po is not None else 0, "Coverage < 45일")
    c4.metric("SO 필요", len(tr) if tr is not None else 0, "FBA Cov < 30일")
    st.divider()
    st.subheader("메뉴")
    cols = st.columns(3)
    menus = [("📦 Amazon Inventory", "Amazon Inventory"), ("📋 Inventory Planning", "Inventory Planning"),
             ("🎵 TikTok Inventory", "TikTok Inventory"), ("📈 Sales", "Sales")]
    for i, (label, target) in enumerate(menus):
        with cols[i % 3]:
            if st.button(label, use_container_width=True):
                st.session_state["menu"] = target
                st.rerun()


def page_amazon_inventory(S, brand):
    st.title("Amazon Inventory")
    st.caption("CCONMA + FBA(세부 컬럼 분리) · Coverage / Status")
    f1, f2 = st.columns(2)
    st.session_state["f_status"] = f1.selectbox("Status", ["전체", "Critical", "Warning", "Healthy"],
                                                index=["전체", "Critical", "Warning", "Healthy"].index(st.session_state.get("f_status", "전체")))
    st.session_state["f_cov"] = f2.selectbox("Coverage", ["전체", "< 30일", "30–60일", "> 60일"],
                                             index=["전체", "< 30일", "30–60일", "> 60일"].index(st.session_state.get("f_cov", "전체")))
    df = apply_filters(S["amazon"], brand, st.session_state.get("query", ""), use_status=True)
    st.caption(f"{len(df)} / {len(S['amazon'])} SKU")
    cols_order = ["SKU", "ASIN", "Product Name", "Brand", "CCONMA"] + FBA_SUBCOLS + \
                 ["FBA_Total", "Total", "7D", "30D", "DailyAvg", "CoverageDays", "Status"]
    if not df.empty:
        df = df[[c for c in cols_order if c in df.columns]]
        st.dataframe(style_status(df), use_container_width=True, height=560)
        download_btn(df, "⬇ CSV Export", f"amazon_inventory_{brand or 'all'}.csv")
    else:
        st.info("재고 데이터 없음 — 사이드바에서 데모를 켜거나 시트를 연동하세요.")


def page_inventory_planning(S, brand):
    st.title("Inventory Planning")
    st.caption("발주 필요 SKU · SO 필요 SKU (CCONMA → FBA)")
    po = apply_filters(S["po"], brand, st.session_state.get("query", ""))
    tr = apply_filters(S["tr"], brand, st.session_state.get("query", ""))
    left, right = st.columns(2)
    with left:
        st.subheader("발주 필요 SKU")
        st.caption("발주량 = Daily Avg × 90 − 현재고 · 발주 후 회전일 = (재고+발주량)/Daily Avg")
        if po is not None and not po.empty:
            st.dataframe(po, use_container_width=True, height=460)
            download_btn(po, "⬇ 발주 CSV", f"purchase_order_{brand or 'all'}.csv")
        else:
            st.info("발주 필요 SKU 없음")
    with right:
        st.subheader("SO 필요 SKU")
        st.caption("이동량 = Daily Avg × 60 − FBA · 조건: FBA Cov < 30 & CCONMA > 0")
        if tr is not None and not tr.empty:
            st.dataframe(tr, use_container_width=True, height=460)
            download_btn(tr, "⬇ SO CSV", f"so_required_{brand or 'all'}.csv")
        else:
            st.info("SO 필요 SKU 없음")


def page_tiktok_inventory(S, brand):
    st.title("TikTok Inventory")
    st.caption("CCONMA(재고 시트_CCONMA 자동 연동) + FBT(업로드)")
    f1, f2 = st.columns(2)
    st.session_state["f_status"] = f1.selectbox("Status", ["전체", "Critical", "Warning", "Healthy"],
                                                index=["전체", "Critical", "Warning", "Healthy"].index(st.session_state.get("f_status", "전체")), key="tt_status")
    st.session_state["f_cov"] = f2.selectbox("Coverage", ["전체", "< 30일", "30–60일", "> 60일"],
                                             index=["전체", "< 30일", "30–60일", "> 60일"].index(st.session_state.get("f_cov", "전체")), key="tt_cov")
    df = apply_filters(S["tiktok"], brand, st.session_state.get("query", ""), use_status=True)
    st.caption(f"{len(df)} / {len(S['tiktok'])} SKU")
    if not df.empty:
        st.dataframe(style_status(df), use_container_width=True, height=520)
        download_btn(df, "⬇ CSV Export", f"tiktok_inventory_{brand or 'all'}.csv")
    else:
        st.info("TikTok 재고 없음 — FBT/판매량 업로드 또는 데모를 켜세요.")


def kpi_row(agg):
    c1, c2, c3, c4 = st.columns(4)
    dt = None
    if agg["r_yest"]:
        dt = f"{(agg['r_today']-agg['r_yest'])/agg['r_yest']*100:.0f}% vs 전일"
    c1.metric("오늘 매출", usd(agg["r_today"]), dt)
    dm = None
    if agg["r_prev_month"]:
        dm = f"{(agg['r_month']-agg['r_prev_month'])/agg['r_prev_month']*100:.0f}% vs 전월"
    c2.metric("이번 달 매출", usd(agg["r_month"]), dm)
    c3.metric("7일 매출", usd(agg["r_7"]), f"일 평균 {usd(agg['r_7']/7)}")
    c4.metric("30일 매출", usd(agg["r_30"]), f"일 평균 {usd(agg['r_30']/30)}")
    u1, u2, u3, u4 = st.columns(4)
    u1.metric("오늘 판매량", fmt(agg["u_today"]))
    u2.metric("7일 판매량", fmt(agg["u_7"]))
    u3.metric("30일 판매량", fmt(agg["u_30"]))
    u4.metric("일 평균(30d)", fmt(agg["u_30"] / 30))


def page_sales(S, brand):
    st.title("Sales Dashboard")
    master = S["master"]
    tab_amz, tab_tt = st.tabs(["Amazon Sales", "TikTok Shop Sales"])

    with tab_amz:
        st.caption(f"Amazon · {brand or '전체 브랜드'} 기준")
        agg = sales_aggregate(master, S["asales"], brand)
        kpi_row(agg)
        st.markdown("##### 브랜드 특화 KPI")
        k1, k2 = st.columns(2)
        nooni = keyword_revenue(master, S["asales"], "NOONI", "lip oil")
        idc = keyword_revenue(master, S["asales"], "I DEW CARE", "tap secret")
        k1.metric("NOONI Lip Oil 매출 (30D)", usd(nooni))
        k2.metric("I DEW CARE Tap Secret 매출 (30D)", usd(idc))
        st.divider()
        daily_line(agg["entries"], "Daily Sales Trend · 30d", COLORS["accent"])
        c1, c2 = st.columns(2)
        with c1:
            sku_df = sku_revenue_table(master, S["asales"], brand).head(10)
            hbar(sku_df, "30D Revenue", "Product Name", "SKU 매출 Top 10 · 30d", COLORS["amz"])
        with c2:
            br = brand_revenue(master, S["asales"]).head(5)
            hbar(br, "Revenue", "Brand", "Brand Revenue · Top 5", COLORS["accent"])
        st.markdown("##### SKU별 매출 분석")
        full = sku_revenue_table(master, S["asales"], brand)
        if not full.empty:
            st.dataframe(full, use_container_width=True, height=360)
            download_btn(full, "⬇ SKU 매출 CSV", f"amazon_sku_sales_{brand or 'all'}.csv")
        else:
            st.info("판매 데이터 없음")

    with tab_tt:
        st.caption(f"TikTok Shop · {brand or '전체 브랜드'} 기준")
        agg = sales_aggregate(master, S["tsales"], brand)
        kpi_row(agg)
        st.divider()
        daily_line(agg["entries"], "TikTok Daily Sales Trend · 30d", COLORS["tt"])
        c1, c2 = st.columns(2)
        with c1:
            sku_df = sku_revenue_table(master, S["tsales"], brand).head(10)
            hbar(sku_df, "30D Revenue", "Product Name", "SKU 매출 Top 10 · 30d", COLORS["tt"])
        with c2:
            br = brand_revenue(master, S["tsales"]).head(5)
            hbar(br, "Revenue", "Brand", "Brand Revenue · Top 5", COLORS["accent"])
        full = sku_revenue_table(master, S["tsales"], brand)
        if not full.empty:
            st.markdown("##### SKU별 매출 분석")
            st.dataframe(full, use_container_width=True, height=360)
            download_btn(full, "⬇ SKU 매출 CSV", f"tiktok_sku_sales_{brand or 'all'}.csv")


# ============================ MAIN ============================
def main():
    st.set_page_config(page_title="Inventory Control", page_icon="📦", layout="wide")

    # session defaults
    st.session_state.setdefault("menu", "Home")
    st.session_state.setdefault("demo", True)
    st.session_state.setdefault("query", "")

    with st.sidebar:
        st.markdown("### 📦 재고 관제")
        st.caption("Inventory Control")
        menu_items = ["Home", "Amazon Inventory", "Inventory Planning", "TikTok Inventory", "Sales"]
        st.session_state["menu"] = st.radio("메뉴", menu_items,
                                            index=menu_items.index(st.session_state.get("menu", "Home")))
        st.divider()

    # load data (after demo toggle is known)
    S = get_state()

    with st.sidebar:
        brands = sorted([b for b in S["master"]["Brand"].unique().tolist() if b])
        brand = st.selectbox("Brand Filter", ["All Brands"] + brands)
        brand = "" if brand == "All Brands" else brand
        st.session_state["query"] = st.text_input("검색 (SKU · ASIN · 제품명)", st.session_state.get("query", ""))
        st.divider()
        st.markdown("##### 데이터 소스")
        st.checkbox("데모 데이터", key="demo")
        st.file_uploader("TikTok FBT 재고 (CSV/XLSX)", type=["csv", "xlsx", "xls"], key="_fbt_file",
                         on_change=lambda: st.session_state.update(up_fbt=_read_upload(st.session_state.get("_fbt_file"))))
        st.file_uploader("TikTok 판매량 (CSV/XLSX)", type=["csv", "xlsx", "xls"], key="_tsales_file",
                         on_change=lambda: st.session_state.update(up_tsales=_read_upload(st.session_state.get("_tsales_file"))))
        st.divider()
        sheet = S["sheet"]
        if sheet["configured"]:
            st.success("Google Sheet 연동됨")
        elif sheet["error"]:
            st.warning(f"연동 안 됨: {sheet['error']}")
        else:
            st.info("데모 / 업로드 모드")
        st.caption(f"마스터 {len(S['master'])} SKU")

    menu = st.session_state["menu"]
    if menu == "Home":
        page_home(S, brand)
    elif menu == "Amazon Inventory":
        page_amazon_inventory(S, brand)
    elif menu == "Inventory Planning":
        page_inventory_planning(S, brand)
    elif menu == "TikTok Inventory":
        page_tiktok_inventory(S, brand)
    elif menu == "Sales":
        page_sales(S, brand)


def _read_upload(file):
    if file is None:
        return None
    try:
        name = file.name.lower()
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(file)
        return pd.read_csv(file)
    except Exception:  # noqa: BLE001
        return None


if _under_streamlit() or __name__ != "__main__":
    main()
