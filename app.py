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
FX_FALLBACK = 1380.0  # 환율 조회 실패 시 사용
DEMO_DAYS = 180  # 데모 판매 이력 길이 — 월별/주별 추이를 보려면 30일보다 길어야 함

COLORS = {"crit": "#F87171", "warn": "#FBBF24", "heal": "#34D399",
          "amz": "#FF9900", "tt": "#FE2C55", "accent": "#2DD4BF"}

# ============================ BRAND ============================
# 브랜드 귀속은 PRODUCT INFO F열(Internal Code)의 접두어를 1순위로 판정한다.
BRAND_UNASSIGNED = "미분류"
BRANDS = ["NOONI", "I DEW CARE", "I'M MEME", "KAJA"]

# Internal Code 접두어 -> 정식 브랜드명 (긴 접두어부터 검사)
BRAND_PREFIX = [
    ("NOONI", "NOONI"),
    ("KAJA", "KAJA"),
    ("IDC", "I DEW CARE"),
    ("IMM", "I'M MEME"),
]

# 브랜드명/제품명/캠페인명 등 자유 텍스트에서 브랜드를 찾을 때 쓰는 별칭
BRAND_ALIASES = {
    "NOONI": ["nooni"],
    "I DEW CARE": ["idewcare", "dewcare", "idc"],
    "I'M MEME": ["immeme", "imeme", "imm", "meme"],
    "KAJA": ["kaja"],
}

BRAND_COLORS = {"NOONI": "#60A5FA", "I DEW CARE": "#34D399",
                "I'M MEME": "#F472B6", "KAJA": "#FBBF24",
                BRAND_UNASSIGNED: "#94A3B8"}

# 광고비(캠페인 단위) 시트/업로드 컬럼 인식 후보
AD_COL = {
    "date": ["date", "날짜", "일자", "start date", "report date"],
    "campaign": ["campaign name", "campaign", "캠페인", "캠페인명", "campaignname"],
    "spend": ["spend", "cost", "광고비", "비용", "total spend", "ad spend", "집행액"],
    "impressions": ["impressions", "impr", "노출수", "노출"],
    "clicks": ["clicks", "click", "클릭수", "클릭"],
    "orders": ["orders", "7 day total orders", "주문수", "주문", "conversions"],
    "adsales": ["7 day total sales", "ad sales", "광고매출", "attributed sales", "sales"],
    "brand": ["brand name", "brand", "브랜드"],
}

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
    "cconma": ["cconma", "cconma inventory", "cconma재고", "cconma 재고", "씨씨온마"],
    "internal": ["internal code", "internalcode", "internal", "internal sku", "internal-code", "내부코드", "관리코드", "사내코드", "internal_code", "내부 코드"],
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


def ifloor(n):
    """Truncate to integer (floor), never round. 15.8 -> 15."""
    try:
        import math
        return int(math.floor(float(n)))
    except (ValueError, TypeError):
        return 0


def fmt(n):
    # All inventory/unit quantities display as floored integers.
    try:
        return f"{ifloor(n):,}"
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


# ============================ BRAND RESOLUTION ============================
def brand_from_internal(code):
    """Internal Code 접두어로 브랜드 판정. 예: 'IDC-32001143' -> 'I DEW CARE'."""
    s = re.sub(r"[^A-Za-z0-9]", "", str("" if code is None else code)).upper()
    if not s:
        return ""
    for pre, brand in BRAND_PREFIX:
        if s.startswith(pre):
            return brand
    return ""


def brand_from_text(txt):
    """브랜드명 / 제품명 / 캠페인명 등 자유 텍스트에서 브랜드 추정.

    ①문자열 시작  ②구분자로 쪼갠 토큰 정확 일치 (예: 'SP_IDC_Auto')
    ③5자 이상 별칭의 부분 일치.
    'IDC' 같은 짧은 약자는 토큰이 정확히 일치할 때만 인정한다 —
    'Shimmer'가 'IMM'에 걸리는 식의 오탐을 막기 위함.
    """
    s = str("" if txt is None else txt)
    n = re.sub(r"[^a-z0-9]", "", s.lower())
    if not n:
        return ""
    for brand, aliases in BRAND_ALIASES.items():
        for a in aliases:
            if n.startswith(a):
                return brand
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]
    cand = set(tokens)
    for i in range(len(tokens)):  # 붙여 읽어야 하는 'i dew care' 대응
        for j in (2, 3):
            if i + j <= len(tokens):
                cand.add("".join(tokens[i:i + j]))
    for brand, aliases in BRAND_ALIASES.items():
        for a in aliases:
            if a in cand:
                return brand
    for brand, aliases in BRAND_ALIASES.items():
        for a in aliases:
            if len(a) >= 5 and a in n:
                return brand
    return ""


def resolve_brand(internal="", brand_raw="", product_name="", sku=""):
    """판정 우선순위: ①Internal Code 접두어 ②Brand Name 컬럼 ③제품명 ④SKU."""
    for fn, val in ((brand_from_internal, internal), (brand_from_text, brand_raw),
                    (brand_from_text, product_name), (brand_from_internal, sku)):
        b = fn(val)
        if b:
            return b
    return BRAND_UNASSIGNED


def brand_source(internal="", brand_raw="", product_name="", sku=""):
    """어떤 근거로 브랜드가 정해졌는지 (Settings 검증용)."""
    if brand_from_internal(internal):
        return "Internal Code"
    if brand_from_text(brand_raw):
        return "Brand Name 컬럼"
    if brand_from_text(product_name):
        return "제품명 추정"
    if brand_from_internal(sku):
        return "SKU 추정"
    return "판정 실패"


def brand_options(master):
    """사이드바/페이지에서 쓸 브랜드 목록 — 항상 4개 고정, 미분류는 있을 때만."""
    present = set(master["Brand"].tolist()) if (master is not None and "Brand" in master.columns) else set()
    out = [b for b in BRANDS if b in present] or list(BRANDS)
    if BRAND_UNASSIGNED in present:
        out = out + [BRAND_UNASSIGNED]
    return out


# ============================ MASTER ============================
@st.cache_data(show_spinner=False)
def load_master_from_csv(csv_text):
    df = pd.read_csv(io.StringIO(csv_text))
    return _master_from_df(df)


def _master_from_df(df):
    ks, kn = pick(df, COL["sku"]), pick(df, COL["name"])
    ka, kb, kp = pick(df, COL["asin"]), pick(df, COL["brand"]), pick(df, COL["price"])
    kic = pick(df, COL["internal"])
    # PRODUCT INFO 탭의 Internal Code는 F열. 헤더명으로 못 찾으면 F열(index 5)을 사용.
    if not kic and len(df.columns) >= 6:
        cand = list(df.columns)[5]
        hits = sum(1 for v in df[cand].tolist() if brand_from_internal(v))
        if hits >= max(1, int(len(df) * 0.3)):
            kic = cand
    rows = []
    for _, r in df.iterrows():
        if not ks:
            continue
        raw = str(r[ks]).strip()
        if not raw or raw.lower() == "nan":
            continue
        sku = clean_sku(raw)
        internal = str(r[kic]).strip() if kic else ""
        if internal.lower() == "nan":
            internal = ""
        brand_raw = str(r[kb]).strip() if kb else ""
        name = str(r[kn]).strip() if kn else sku
        rows.append({
            "SKU": sku,
            "Internal Code": internal,
            "ASIN": str(r[ka]).strip() if ka else "",
            "Product Name": name,
            "Brand": resolve_brand(internal, brand_raw, name, sku),
            "Brand Raw": brand_raw,
            "Brand Source": brand_source(internal, brand_raw, name, sku),
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
def read_sheet(sheet_id, _auth_key):
    out = {"configured": False, "error": None,
           "cconma": pd.DataFrame(), "fba": pd.DataFrame(),
           "sales": pd.DataFrame(), "master": pd.DataFrame(),
           "ads": pd.DataFrame(), "detected": {}}
    if not sheet_id:
        out["error"] = "GOOGLE_SHEET_ID 미설정"
        return out

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    try:
        from googleapiclient.discovery import build
        if api_key:
            svc = build("sheets", "v4", developerKey=api_key, cache_discovery=False)
        else:
            creds, err = _credentials()
            if err:
                out["error"] = err
                return out
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
            elif "ads" not in role and (has(t, "광고") or has(t, "campaign") or has(t, "advertis")
                                        or norm(t) in ("ad", "ads", "adspend")):
                role["ads"] = t
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
def index_inv(df, qty_cands=None):
    """sku -> qty. qty_cands lets the caller force a specific column (e.g. 'CCONMA')."""
    res = {}
    if df is None or df.empty:
        return res
    ks = pick(df, COL["sku"])
    kq = pick(df, qty_cands if qty_cands else COL["qty"])
    if not ks:
        return res
    for _, r in df.iterrows():
        sku = clean_sku(r[ks])
        if not sku:
            continue
        res[sku] = res.get(sku, 0.0) + (numv(r[kq]) if kq else 0.0)
    return res


def _row_keys(r, ks, ki, ka):
    internal = clean_sku(r[ki]) if ki else ""
    sku = clean_sku(r[ks]) if ks else ""
    asin = str(r[ka]).strip() if ka else ""
    return internal, sku, asin


def find_cconma_col(df):
    """1) exact name 'CCONMA'  2) name contains 'CCONMA'  3) M column (index 12)."""
    cols = list(df.columns)
    for c in cols:
        if norm(c) == "cconma":
            return c, "이름 정확 일치 ('CCONMA')"
    for c in cols:
        if "cconma" in norm(c):
            return c, f"이름 포함 ('{c}')"
    if len(cols) >= 13:
        return cols[12], f"M열 사용 ('{cols[12]}')"
    return None, "해당 컬럼 없음"


def index_cconma(df):
    """Keyed CCONMA index: by internal/sku/asin -> qty, plus validation metadata."""
    info = {"columns": [], "n_rows": 0, "col": None, "col_method": "해당 컬럼 없음",
            "total_qty": 0.0, "by_internal": {}, "by_sku": {}, "by_asin": {}, "rows": []}
    if df is None or df.empty:
        return info
    info["columns"] = [str(c) for c in df.columns]
    info["n_rows"] = int(len(df))
    col, method = find_cconma_col(df)
    info["col"], info["col_method"] = col, method
    ks, ki, ka = pick(df, COL["sku"]), pick(df, COL["internal"]), pick(df, COL["asin"])
    kb, kn = pick(df, COL["brand"]), pick(df, COL["name"])
    for _, r in df.iterrows():
        internal, sku, asin = _row_keys(r, ks, ki, ka)
        qty = numv(r[col]) if col else 0.0
        info["total_qty"] += qty
        if internal:
            info["by_internal"][internal] = info["by_internal"].get(internal, 0.0) + qty
        if sku:
            info["by_sku"][sku] = info["by_sku"].get(sku, 0.0) + qty
        if asin:
            info["by_asin"][asin] = info["by_asin"].get(asin, 0.0) + qty
        info["rows"].append({"internal": internal, "sku": sku, "asin": asin, "qty": qty,
                             "brand": str(r[kb]).strip() if kb else "",
                             "name": str(r[kn]).strip() if kn else ""})
    return info


def index_fba(df):
    """Keyed FBA index: by internal/sku/asin -> {sub-col: qty}."""
    info = {"columns": [], "n_rows": 0, "by_internal": {}, "by_sku": {}, "by_asin": {}}
    if df is None or df.empty:
        return info
    info["columns"] = [str(c) for c in df.columns]
    info["n_rows"] = int(len(df))
    ks, ki, ka = pick(df, COL["sku"]), pick(df, COL["internal"]), pick(df, COL["asin"])
    found = {k: pick(df, v) for k, v in FBA_MATCH.items()}
    for _, r in df.iterrows():
        internal, sku, asin = _row_keys(r, ks, ki, ka)
        sub = {c: (numv(r[found[c]]) if found[c] else 0.0) for c in FBA_SUBCOLS}
        for key, store in [(internal, "by_internal"), (sku, "by_sku"), (asin, "by_asin")]:
            if not key:
                continue
            d = info[store].setdefault(key, {c: 0.0 for c in FBA_SUBCOLS})
            for c in FBA_SUBCOLS:
                d[c] += sub[c]
    return info


def resolve(idx, internal, sku, asin, default):
    """Match priority: Internal Code -> SKU (SAP CODE) -> ASIN. Returns (value, matched_key)."""
    if internal and internal in idx.get("by_internal", {}):
        return idx["by_internal"][internal], "Internal Code"
    if sku and sku in idx.get("by_sku", {}):
        return idx["by_sku"][sku], "SKU"
    if asin and asin in idx.get("by_asin", {}):
        return idx["by_asin"][asin], "ASIN"
    return default, None


def index_ads(df):
    """캠페인 단위 광고비 -> 정규화된 DataFrame.

    컬럼: Date / Campaign / Brand / Spend / Impressions / Clicks / Orders / Ad Sales
    브랜드는 ①Brand 컬럼 ②캠페인명 안의 브랜드 키워드 순으로 판정한다.
    """
    empty = pd.DataFrame(columns=["Date", "Campaign", "Brand", "Spend",
                                  "Impressions", "Clicks", "Orders", "Ad Sales"])
    if df is None or df.empty:
        return empty
    kd, kc = pick(df, AD_COL["date"]), pick(df, AD_COL["campaign"])
    ksp = pick(df, AD_COL["spend"])
    ki, kcl = pick(df, AD_COL["impressions"]), pick(df, AD_COL["clicks"])
    ko, kas = pick(df, AD_COL["orders"]), pick(df, AD_COL["adsales"])
    kb = pick(df, AD_COL["brand"])
    if not ksp:
        return empty
    rows = []
    for _, r in df.iterrows():
        camp = str(r[kc]).strip() if kc else ""
        brand_raw = str(r[kb]).strip() if kb else ""
        brand = brand_from_text(brand_raw) or brand_from_text(camp) or BRAND_UNASSIGNED
        try:
            dt = pd.to_datetime(r[kd]) if kd else pd.NaT
        except Exception:  # noqa: BLE001
            dt = pd.NaT
        rows.append({
            "Date": dt.strftime("%Y-%m-%d") if dt is not pd.NaT and not pd.isna(dt) else "",
            "Campaign": camp, "Brand": brand,
            "Spend": numv(r[ksp]),
            "Impressions": numv(r[ki]) if ki else 0.0,
            "Clicks": numv(r[kcl]) if kcl else 0.0,
            "Orders": numv(r[ko]) if ko else 0.0,
            "Ad Sales": numv(r[kas]) if kas else 0.0,
        })
    out = pd.DataFrame(rows)
    return out if not out.empty else empty


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
        for d in range(DEMO_DAYS - 1, -1, -1):
            dt = now - timedelta(days=d)
            wk = 1.25 if dt.weekday() >= 5 else 1.0
            # 완만한 성장 + 월 단위 굴곡을 넣어 월별/주별 추이가 의미를 갖게 한다
            trend = 0.75 + 0.5 * (DEMO_DAYS - d) / DEMO_DAYS
            seas = 1.0 + 0.18 * ((dt.month * 7 + i) % 5 - 2) / 2.0
            u = max(0, round(velo * wk * trend * seas * (0.5 + rnd.random())))
            tu = max(0, round(tvelo * wk * trend * seas * (0.5 + rnd.random())))
            if d < 30:
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
def build_dataframes(master, cc_idx, fba_idx, asales, tfbt_map, tsales):
    amazon_rows, tiktok_rows, po_rows, tr_rows = [], [], [], []
    zero_fba = {c: 0.0 for c in FBA_SUBCOLS}
    for _, p in master.iterrows():
        sku = clean_sku(p["SKU"])
        internal = clean_sku(p.get("Internal Code", "")) if "Internal Code" in master.columns else ""
        asin = str(p.get("ASIN", "")).strip()
        # Match priority: Internal Code -> SKU (SAP CODE) -> ASIN
        cc, _cc_key = resolve(cc_idx, internal, sku, asin, 0.0)
        fb, _fb_key = resolve(fba_idx, internal, sku, asin, zero_fba)

        fba_available = ifloor(fb.get("FBA_Available", 0.0))
        fba_inbound = ifloor(fb.get("FBA_inbound_working", 0.0)
                             + fb.get("FBA_inbound_shipped", 0.0)
                             + fb.get("FBA_inbound_receiving", 0.0))
        fba_reserved = ifloor(fb.get("FBA_reserved_processing", 0.0)
                              + fb.get("FBA_reserved_transfer", 0.0))
        fba_reserved_orders = ifloor(fb.get("FBA_reserved_orders", 0.0))
        # Total FBA = Available + Inbound + Reserved(processing+transfer); Reserved Orders EXCLUDED.
        total_fba = fba_available + fba_inbound + fba_reserved
        cc_i = ifloor(cc)
        # Total Inventory = CCONMA + Total FBA  (sums of the displayed integers)
        total = cc_i + total_fba

        sp = asales.get(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
        s7, s30 = sp["s7"], sp["s30"]
        da = s30 / 30.0
        cov = (total / da) if da > 0 else (999 if total > 0 else 0)
        fba_cov = (total_fba / da) if da > 0 else (999 if total_fba > 0 else 0)
        st_ = status_of(cov)
        if cc_i or total_fba or fba_reserved_orders or s30 or s7:
            row = {"SKU": sku, "Internal Code": p.get("Internal Code", "") if "Internal Code" in master.columns else "",
                   "ASIN": p["ASIN"], "Product Name": p["Product Name"],
                   "Brand": p["Brand"],
                   "CCONMA Inventory": cc_i,
                   "FBA Available": fba_available,
                   "FBA Inbound": fba_inbound,
                   "FBA Reserved": fba_reserved,
                   "FBA Reserved Orders": fba_reserved_orders,
                   "Total FBA Inventory": total_fba,
                   "Total Inventory": total,
                   "CoverageDays": round(cov) if cov < 999 else 999, "Status": st_,
                   "7D": ifloor(s7), "30D": ifloor(s30), "DailyAvg": round(da, 2)}
            amazon_rows.append(row)
            if cov < PO_THRESHOLD:
                rec = max(0, round(da * PO_TARGET_DAYS - total))
                cov_after = round((total + rec) / da) if da > 0 else 999
                po_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                "Current Inventory": total, "DailyAvg": round(da, 2),
                                "CoverageDays": round(cov) if cov < 999 else 999,
                                "Recommended Order Qty": ifloor(rec), "발주 후 회전일": cov_after})
            if fba_cov < TR_FBA_DAYS and cc_i > 0:
                rec = max(0, min(cc_i, round(da * TR_TARGET_DAYS - total_fba)))
                if rec > 0:
                    tr_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                    "FBA Inventory": total_fba, "CCONMA Inventory": cc_i,
                                    "Recommended Transfer Qty": ifloor(rec)})
        # TikTok — CCONMA from the same 재고 시트_CCONMA (resolved above)
        tcc = cc_i
        tfbt = tfbt_map.get(sku, 0.0)
        tsp = tsales.get(sku, {"s7": 0.0, "s30": 0.0, "daily": {}})
        t7, t30 = tsp["s7"], tsp["s30"]
        tda = t30 / 30.0
        ttotal = tcc + tfbt
        tcov = (ttotal / tda) if tda > 0 else (999 if ttotal > 0 else 0)
        if tcc or tfbt or t30 or t7:
            tiktok_rows.append({"SKU": sku, "Product Name": p["Product Name"], "Brand": p["Brand"],
                                "CCONMA": ifloor(tcc), "FBT": ifloor(tfbt), "Total": ifloor(ttotal),
                                "7D": ifloor(t7), "30D": ifloor(t30), "DailyAvg": round(tda, 2),
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
        # 실제 날짜 창 기준 — 판매가 없는 날이 빠져도 기간이 늘어나지 않는다
        cut = window_start(n)
        return sum(v[f] for k, v in daily.items() if k >= cut)

    r_month = sum(v["rev"] for k, v in daily.items() if k[:7] == this_m)
    r_prev = sum(v["rev"] for k, v in daily.items() if k[:7] == prev_m)
    return {
        "entries": entries[-30:],
        "u_today": g(today, "u"), "u_7": last(7, "u"), "u_30": last(30, "u"),
        "r_today": g(today, "rev"), "r_yest": g(yest, "rev"),
        "r_7": last(7, "rev"), "r_30": last(30, "rev"),
        "r_month": r_month, "r_prev_month": r_prev,
    }


def sku_revenue_table(master, sales, brand, days=30):
    cut = window_start(days) if days else ""
    bybrand = {r["SKU"]: (r["Brand"], r["Product Name"]) for _, r in master.iterrows()}
    rows = []
    for sku, o in sales.items():
        b, nm = bybrand.get(sku, ("", sku))
        if brand and b != brand:
            continue
        rev = sum(c["rev"] for dk, c in o.get("daily", {}).items() if not cut or dk >= cut)
        units = sum(c["u"] for dk, c in o.get("daily", {}).items() if not cut or dk >= cut)
        if rev or units:
            rows.append({"SKU": sku, "Product Name": nm, "Brand": b,
                         "30D Units": round(units), "30D Revenue": round(rev)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("30D Revenue", ascending=False).reset_index(drop=True)
    return df


def brand_revenue(master, sales, days=30):
    cut = window_start(days) if days else ""
    bybrand = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    agg = {}
    for sku, o in sales.items():
        b = bybrand.get(sku, "")
        if not b:
            continue
        rev = sum(c["rev"] for dk, c in o.get("daily", {}).items() if not cut or dk >= cut)
        agg[b] = agg.get(b, 0.0) + rev
    df = pd.DataFrame([{"Brand": k, "Revenue": round(v)} for k, v in agg.items()])
    if not df.empty:
        df = df.sort_values("Revenue", ascending=False).reset_index(drop=True)
    return df


# ============================ BRAND AGGREGATION ============================
def window_start(days):
    """ISO 날짜 문자열 비교용 시작일 (오늘 포함 최근 days일)."""
    return (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")


def _sales_totals(sales, skus, days=30):
    """(units, revenue) — 최근 days일. daily가 없으면 s30 집계값으로 대체."""
    cut = window_start(days)
    units = rev = 0.0
    for s in skus:
        o = sales.get(s)
        if not o:
            continue
        daily = o.get("daily", {})
        if daily:
            for dk, c in daily.items():
                if dk >= cut:
                    units += c["u"]
                    rev += c["rev"]
        else:
            units += o.get("s30", 0.0)
    return units, rev


def brand_daily(master, sales, days=30):
    """브랜드 × 날짜 매출/판매량 시계열."""
    cut = window_start(days) if days else ""
    bmap = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    acc = {}
    for sku, o in sales.items():
        b = bmap.get(sku, BRAND_UNASSIGNED)
        for dk, cell in o.get("daily", {}).items():
            if cut and dk < cut:
                continue
            k = (dk, b)
            d = acc.setdefault(k, {"units": 0.0, "revenue": 0.0})
            d["units"] += cell["u"]
            d["revenue"] += cell["rev"]
    rows = [{"date": dk, "Brand": b, "units": v["units"], "revenue": v["revenue"]}
            for (dk, b), v in sorted(acc.items())]
    return pd.DataFrame(rows)


def ads_by_brand(ads):
    """브랜드별 광고 지표 합계."""
    cols = ["Brand", "Spend", "Impressions", "Clicks", "Orders", "Ad Sales", "Campaigns"]
    if ads is None or ads.empty:
        return pd.DataFrame(columns=cols)
    g = ads.groupby("Brand", dropna=False).agg(
        Spend=("Spend", "sum"), Impressions=("Impressions", "sum"),
        Clicks=("Clicks", "sum"), Orders=("Orders", "sum"),
        **{"Ad Sales": ("Ad Sales", "sum")},
        Campaigns=("Campaign", "nunique")).reset_index()
    return g[cols]


def brand_rollup(master, amazon, tiktok, asales, tsales, ads):
    """브랜드 단위 통합 성과표 — 매출 · 판매량 · 광고비 · 재고."""
    bmap = {}
    for _, r in master.iterrows():
        bmap.setdefault(r["Brand"], []).append(r["SKU"])
    adf = ads_by_brand(ads).set_index("Brand") if (ads is not None and not ads.empty) else None

    rows = []
    for b in brand_options(master):
        skus = bmap.get(b, [])
        a_u, a_rev = _sales_totals(asales, skus)
        t_u, t_rev = _sales_totals(tsales, skus)
        amz_b = amazon[amazon["Brand"] == b] if (amazon is not None and not amazon.empty) else pd.DataFrame()
        tt_b = tiktok[tiktok["Brand"] == b] if (tiktok is not None and not tiktok.empty) else pd.DataFrame()
        spend = float(adf.loc[b, "Spend"]) if (adf is not None and b in adf.index) else 0.0
        ad_sales = float(adf.loc[b, "Ad Sales"]) if (adf is not None and b in adf.index) else 0.0
        total_rev = a_rev + t_rev
        rows.append({
            "Brand": b,
            "SKU 수": len(skus),
            "Amazon 판매량 (30D)": ifloor(a_u),
            "Amazon 매출 (30D)": round(a_rev),
            "TikTok 판매량 (30D)": ifloor(t_u),
            "TikTok 매출 (30D)": round(t_rev),
            "총 매출 (30D)": round(total_rev),
            "광고비 (30D)": round(spend),
            "광고매출 (30D)": round(ad_sales),
            "ACOS": round(spend / ad_sales * 100, 1) if ad_sales else None,
            "광고비 비중": round(spend / total_rev * 100, 1) if total_rev else None,
            "총 재고": ifloor(amz_b["Total Inventory"].sum()) if "Total Inventory" in amz_b.columns else 0,
            "Critical SKU": int((amz_b["Status"] == "Critical").sum()) if "Status" in amz_b.columns else 0,
            "TikTok 재고": ifloor(tt_b["Total"].sum()) if "Total" in tt_b.columns else 0,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("총 매출 (30D)", ascending=False).reset_index(drop=True)
    return df


def keyword_revenue(master, sales, brand_kw, name_kw, days=30):
    """Sum 30D revenue for SKUs whose brand+name match the keywords."""
    cut = window_start(days) if days else ""
    total = 0.0
    info = {r["SKU"]: (r["Brand"], r["Product Name"]) for _, r in master.iterrows()}
    for sku, o in sales.items():
        b, nm = info.get(sku, ("", ""))
        if brand_kw.lower() in b.lower() and name_kw.lower() in nm.lower():
            total += sum(c["rev"] for dk, c in o.get("daily", {}).items() if not cut or dk >= cut)
    return total


# ============================ DATA ORCHESTRATION ============================
def get_state():
    sheet = read_sheet(SHEET_ID, os.environ.get("GOOGLE_API_KEY", "") or SA_JSON[:24])
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

    # ---- CCONMA: keyed index (Internal Code -> SKU -> ASIN) ----
    if not sheet["cconma"].empty:
        cc_idx = index_cconma(sheet["cconma"])
    elif demo:
        cc_idx = {"columns": ["SKU", "CCONMA"], "n_rows": len(demo["cc"]),
                  "col": "CCONMA (demo)", "col_method": "데모 데이터",
                  "total_qty": float(sum(demo["cc"].values())),
                  "by_internal": {}, "by_sku": dict(demo["cc"]), "by_asin": {},
                  "rows": [{"internal": "", "sku": k, "asin": "", "qty": v, "brand": "", "name": ""} for k, v in demo["cc"].items()]}
    else:
        cc_idx = index_cconma(pd.DataFrame())

    # ---- FBA: keyed index ----
    if not sheet["fba"].empty:
        fba_idx = index_fba(sheet["fba"])
    elif demo:
        fba_idx = {"columns": list(FBA_SUBCOLS), "n_rows": len(demo["fba"]),
                   "by_internal": {}, "by_sku": dict(demo["fba"]), "by_asin": {}}
    else:
        fba_idx = index_fba(pd.DataFrame())

    asales = index_sales(sheet["sales"]) if not sheet["sales"].empty else (demo["asales"] if demo else {})

    up_fbt = st.session_state.get("up_fbt")
    up_tsales = st.session_state.get("up_tsales")
    tfbt_map = index_inv(up_fbt) if up_fbt is not None else (demo["tfbt"] if demo else {})
    tsales = index_sales(up_tsales) if up_tsales is not None else (demo["tsales"] if demo else {})

    # ---- 광고비(캠페인 단위): 업로드 우선, 없으면 시트의 광고 탭 ----
    up_ads = st.session_state.get("up_ads")
    if up_ads is not None:
        ads = index_ads(up_ads)
        ads_src = "업로드"
    elif not sheet["ads"].empty:
        ads = index_ads(sheet["ads"])
        ads_src = f"Google Sheet ({sheet.get('detected', {}).get('ads', '광고 탭')})"
    else:
        ads = index_ads(pd.DataFrame())
        ads_src = "없음"

    amazon, tiktok, po, tr = build_dataframes(master, cc_idx, fba_idx, asales, tfbt_map, tsales)
    validation = compute_validation(master, cc_idx, sheet)
    return {"sheet": sheet, "master": master, "amazon": amazon, "tiktok": tiktok,
            "po": po, "tr": tr, "asales": asales, "tsales": tsales,
            "cc_idx": cc_idx, "fba_idx": fba_idx, "validation": validation,
            "ads": ads, "ads_src": ads_src}


def compute_validation(master, cc_idx, sheet):
    """Build the Data Validation summary + failed-match table for CCONMA."""
    m_int = set(x for x in master["Internal Code"].tolist() if x) if "Internal Code" in master.columns else set()
    m_int = set(clean_sku(x) for x in m_int if str(x).strip())
    m_sku = set(clean_sku(x) for x in master["SKU"].tolist() if str(x).strip())
    m_asin = set(str(x).strip() for x in master["ASIN"].tolist() if str(x).strip())
    matched, failed_rows = 0, []
    for r in cc_idx.get("rows", []):
        hit = (r["internal"] and r["internal"] in m_int) or (r["sku"] and r["sku"] in m_sku) or (r["asin"] and r["asin"] in m_asin)
        if hit:
            matched += 1
        else:
            if r["qty"] or r["sku"] or r["internal"]:
                reason = []
                if not r["internal"]:
                    reason.append("Internal 없음")
                elif r["internal"] not in m_int:
                    reason.append("Internal 불일치")
                if r["sku"] and r["sku"] not in m_sku:
                    reason.append("SKU 불일치")
                if r["asin"] and r["asin"] not in m_asin:
                    reason.append("ASIN 불일치")
                failed_rows.append({"Brand": r["brand"], "Internal Code": r["internal"],
                                    "SKU": r["sku"], "Product Name": r["name"],
                                    "CCONMA Qty": ifloor(r["qty"]),
                                    "매칭 실패 사유": ", ".join(reason) or "마스터 매칭 실패"})
    return {"matched": matched, "failed": len(failed_rows),
            "failed_rows": pd.DataFrame(failed_rows), "cc_total": ifloor(cc_idx.get("total_qty", 0))}


def apply_filters(df, brand, query, use_status=False, fs="전체", fc="전체"):
    if df is None or df.empty:
        return df
    out = df
    if brand:
        out = out[out["Brand"] == brand]
    if query:
        q = query.strip().lower()
        cols = [c for c in ["Internal Code", "SKU", "ASIN", "Product Name"] if c in out.columns]
        mask = False
        for c in cols:
            mask = mask | out[c].astype(str).str.lower().str.contains(q, na=False)
        out = out[mask]
    if use_status:
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


def daily_line(entries, title, color, key=None):
    if not entries:
        st.info("일별 데이터 없음")
        return
    df = pd.DataFrame([{"date": k, "units": v["u"], "revenue": v["rev"]} for k, v in entries])
    fig = px.area(df, x="date", y="units", title=title)
    fig.update_traces(line_color=color, fillcolor=color.replace(")", ", 0.15)").replace("rgb", "rgba") if color.startswith("rgb") else color)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=40, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, key=key)


def hbar(df, x, y, title, color, key=None):
    if df is None or df.empty:
        st.info("데이터 없음")
        return
    fig = px.bar(df, x=x, y=y, orientation="h", title=title)
    fig.update_traces(marker_color=color)
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis=dict(autorange="reversed"),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, key=key)


def download_btn(df, label, name):
    if df is None or df.empty:
        return
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, csv, file_name=name, mime="text/csv")


# ============================ ELROEL STYLE UI ============================
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_usd_krw(year, month):
    """해당 월의 USD/KRW 평균 환율 (1일·15일·말일 샘플). 실패 시 None."""
    env = os.environ.get("USD_KRW_RATE", "").strip()
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    import calendar
    import urllib.request
    last_day = calendar.monthrange(year, month)[1]
    rates = []
    for day in (1, 15, last_day):
        url = (f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@"
               f"{year}-{month:02d}-{day:02d}/v1/currencies/usd.json")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                krw = json.loads(r.read()).get("usd", {}).get("krw")
            if krw:
                rates.append(float(krw))
        except Exception:  # noqa: BLE001
            continue
    return round(sum(rates) / len(rates), 1) if rates else None


def get_rate():
    now = datetime.now()
    return fetch_usd_krw(now.year, now.month) or FX_FALLBACK


def krw_short(usd, rate):
    """$ 금액을 억/만 단위 원화 문자열로."""
    try:
        usd = float(usd)
    except (ValueError, TypeError):
        return ""
    if usd <= 0:
        return ""
    w = usd * rate
    if w >= 100_000_000:
        return f"₩{w / 100_000_000:.1f}억"
    if w >= 10_000:
        return f"₩{w / 10_000:,.0f}만"
    return f"₩{w:,.0f}"


def metric_pair(c_main, c_side, label, value, delta=None, krw_usd=None,
                rate=None, sub_label=None, sub_value=None, note=None, help=None):
    """ELROEL 스타일: 큰 지표 + 옆칸에 원화 환산 / 일 평균 보조 정보."""
    with c_main:
        st.metric(label, value, delta=delta, help=help)
    with c_side:
        html = ""
        if krw_usd and rate:
            k = krw_short(krw_usd, rate)
            if k:
                html += f"<p style='margin-top:1.2rem;font-size:0.8rem;color:gray'>{k}</p>"
        if sub_label:
            top = "0.1rem" if html else "1.2rem"
            html += (f"<p style='margin-top:{top};font-size:0.75rem;color:#9ca3af'>"
                     f"📊 {sub_label}<br>{sub_value}</p>")
        if note:
            html += f"<p style='margin-top:0.1rem;font-size:0.7rem;color:#6b7280'>{note}</p>"
        if html:
            st.markdown(html, unsafe_allow_html=True)


def render_frozen_table(df, frozen_cols=2, height=460, is_currency=False, today_col=None):
    """좌측 열 고정 + 헤더 고정 스크롤 테이블 (ELROEL 스타일)."""
    frozen_w, col_w = 190, 92

    def _fmt(val, i):
        if i < frozen_cols:
            return str(val)
        try:
            num = float(val)
            if num != num:
                return "-"
            if is_currency:
                return f"${num:,.0f}"
            return f"{int(num):,}" if num == int(num) else f"{num:,.2f}"
        except (ValueError, TypeError):
            return str(val)

    head = ""
    for i, col in enumerate(df.columns):
        frozen = i < frozen_cols
        w = frozen_w if frozen else col_w
        pos = (f"position:sticky;left:{i * frozen_w}px;z-index:10;" if frozen
               else "position:sticky;z-index:8;")
        hl = "background:#1a5c2a!important;color:#7fff7f;" if col == today_col else ""
        head += (f'<th style="padding:6px 8px;text-align:center;white-space:nowrap;'
                 f'border-bottom:2px solid #4a6fa5;font-size:0.78rem;background:#1e3a5f;'
                 f'min-width:{w}px;width:{w}px;box-sizing:border-box;{pos}{hl}">{col}</th>')

    body = ""
    for ri, (_, row) in enumerate(df.iterrows()):
        is_sum = str(row.iloc[0]).startswith("📊")
        bg = "#1a2a3a" if is_sum else ("#16213e" if ri % 2 == 0 else "#1a2744")
        cells = ""
        for ci, (col, val) in enumerate(row.items()):
            frozen = ci < frozen_cols
            w = frozen_w if frozen else col_w
            pos = (f"position:sticky;left:{ci * frozen_w}px;z-index:2;background:{bg};"
                   f"min-width:{w}px;max-width:{w}px;overflow:hidden;text-overflow:ellipsis;"
                   if frozen else f"min-width:{w}px;")
            hl = "background:#0d2b12!important;color:#7fff7f;" if col == today_col else ""
            sm = "font-weight:bold;color:#7fc4ff;" if is_sum else ""
            cells += (f'<td style="padding:5px 8px;text-align:{"left" if frozen else "right"};'
                      f'white-space:nowrap;font-size:0.78rem;border-bottom:1px solid #2a3a4a;'
                      f'{pos}{hl}{sm}">{_fmt(val, ci)}</td>')
        body += f'<tr style="background:{bg}">{cells}</tr>'

    st.html(f"""
    <div style="overflow:auto;height:{height}px;border:1px solid #2a3a4a;border-radius:6px;">
      <table style="border-collapse:collapse;width:max-content;background:#16213e;color:#e0e8f0;">
        <thead style="position:sticky;top:0;z-index:9;"><tr style="background:#1e3a5f;">{head}</tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>""")


# ============================ PERIOD AGGREGATION ============================
def sales_timeseries(master, sales, brand=None):
    """브랜드 필터가 적용된 일별 매출/판매량 시계열."""
    bmap = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    acc = {}
    for sku, o in sales.items():
        if brand and bmap.get(sku, "") != brand:
            continue
        for dk, cell in o.get("daily", {}).items():
            a = acc.setdefault(dk, [0.0, 0.0])
            a[0] += cell["u"]
            a[1] += cell["rev"]
    if not acc:
        return pd.DataFrame(columns=["date", "units", "revenue"])
    rows = [{"date": pd.to_datetime(k), "units": v[0], "revenue": v[1]}
            for k, v in sorted(acc.items())]
    return pd.DataFrame(rows)


def _period_days(p):
    """기간의 일수. 진행 중인 기간이면 오늘까지의 경과 일수."""
    today = datetime.now().date()
    start, end = p.start_time.date(), p.end_time.date()
    if end > today:
        return max((today - start).days + 1, 1)
    return (end - start).days + 1


def agg_period(ts, period="monthly"):
    """일별 시계열 -> 월별/주별 집계 (매출 · 판매량 · 일평균 · 증감률)."""
    cols = ["기간", "_p", "revenue", "units", "days", "일 평균", "변화율"]
    if ts is None or ts.empty:
        return pd.DataFrame(columns=cols)
    df = ts.copy()
    if period == "monthly":
        df["_p"] = df["date"].dt.to_period("M")
    else:
        df["_p"] = df["date"].dt.to_period("W")
    g = df.groupby("_p", as_index=False).agg(revenue=("revenue", "sum"),
                                             units=("units", "sum"))
    g = g.sort_values("_p").reset_index(drop=True)
    if period == "monthly":
        g["기간"] = g["_p"].apply(lambda p: f"{p.year}년 {p.month}월")
    else:
        g["기간"] = g["_p"].apply(
            lambda p: f"{p.start_time.month}/{p.start_time.day}~{p.end_time.month}/{p.end_time.day}")
    g["days"] = g["_p"].apply(_period_days)
    g["일 평균"] = g.apply(lambda r: r["revenue"] / r["days"] if r["days"] else None, axis=1)
    g["변화율"] = g["revenue"].pct_change() * 100
    return g[cols]


def ads_by_period(ads, period="monthly", brand=None):
    """기간 라벨 -> {spend, adsales}. 날짜가 없는 광고 행은 제외."""
    out = {}
    if ads is None or ads.empty or "Date" not in ads.columns:
        return out
    df = ads[ads["Date"].astype(str).str.len() > 0].copy()
    if brand:
        df = df[df["Brand"] == brand]
    if df.empty:
        return out
    df["_dt"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["_dt"])
    if df.empty:
        return out
    if period == "monthly":
        df["_p"] = df["_dt"].dt.to_period("M")
        df["기간"] = df["_p"].apply(lambda p: f"{p.year}년 {p.month}월")
    else:
        df["_p"] = df["_dt"].dt.to_period("W")
        df["기간"] = df["_p"].apply(
            lambda p: f"{p.start_time.month}/{p.start_time.day}~{p.end_time.month}/{p.end_time.day}")
    for label, grp in df.groupby("기간"):
        out[label] = {"spend": float(grp["Spend"].sum()),
                      "adsales": float(grp["Ad Sales"].sum())}
    return out


def brand_period_matrix(master, sales, period="monthly", brand=None):
    """브랜드 × 기간 매출 행렬 (ELROEL의 계정별 비교 차트에 대응)."""
    bmap = {r["SKU"]: r["Brand"] for _, r in master.iterrows()}
    acc = {}
    for sku, o in sales.items():
        b = bmap.get(sku, BRAND_UNASSIGNED)
        if brand and b != brand:
            continue
        for dk, cell in o.get("daily", {}).items():
            acc.setdefault(b, {}).setdefault(dk, 0.0)
            acc[b][dk] += cell["rev"]
    rows = []
    for b, days in acc.items():
        for dk, rev in days.items():
            rows.append({"Brand": b, "date": pd.to_datetime(dk), "revenue": rev})
    if not rows:
        return pd.DataFrame(columns=["Brand", "기간", "revenue"])
    df = pd.DataFrame(rows)
    if period == "monthly":
        df["_p"] = df["date"].dt.to_period("M")
        df["기간"] = df["_p"].apply(lambda p: f"{p.year}년 {p.month}월")
    else:
        df["_p"] = df["date"].dt.to_period("W")
        df["기간"] = df["_p"].apply(
            lambda p: f"{p.start_time.month}/{p.start_time.day}~{p.end_time.month}/{p.end_time.day}")
    g = df.groupby(["Brand", "기간", "_p"], as_index=False)["revenue"].sum()
    return g.sort_values("_p").reset_index(drop=True)


def product_period_pivot(master, sales, period="monthly", brand=None, metric="revenue", top=40):
    """제품 × 기간 행렬 + 합계 행 (고정열 테이블용)."""
    info = {r["SKU"]: (r["Brand"], r["Product Name"]) for _, r in master.iterrows()}
    rows = []
    for sku, o in sales.items():
        b, nm = info.get(sku, (BRAND_UNASSIGNED, sku))
        if brand and b != brand:
            continue
        for dk, cell in o.get("daily", {}).items():
            rows.append({"Brand": b, "제품명": nm, "date": pd.to_datetime(dk),
                         "val": cell["rev"] if metric == "revenue" else cell["u"]})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if period == "monthly":
        df["_p"] = df["date"].dt.to_period("M")
        df["기간"] = df["_p"].apply(lambda p: f"{p.year}-{p.month:02d}")
    else:
        df["_p"] = df["date"].dt.to_period("W")
        df["기간"] = df["_p"].apply(lambda p: p.start_time.strftime("%m/%d"))
    order = df.drop_duplicates("_p").sort_values("_p")["기간"].tolist()
    piv = df.pivot_table(index=["Brand", "제품명"], columns="기간",
                         values="val", aggfunc="sum", fill_value=0).reset_index()
    piv = piv[["Brand", "제품명"] + [c for c in order if c in piv.columns]]
    piv["_tot"] = piv[[c for c in order if c in piv.columns]].sum(axis=1)
    piv = piv.sort_values("_tot", ascending=False).head(top).drop(columns=["_tot"])
    total = {"Brand": "📊 합계", "제품명": ""}
    for c in order:
        if c in piv.columns:
            total[c] = piv[c].sum()
    return pd.concat([pd.DataFrame([total]), piv], ignore_index=True)


# ============================ PAGES ============================
def page_home(S, brand):
    st.title("📊 재고 · 판매 통합 대시보드")
    sheet = S["sheet"]
    src = "Google Sheet 연동" if sheet["configured"] else ("데모 데이터" if st.session_state.get("demo", True) else "업로드 데이터")
    st.caption(f"Amazon + TikTok Shop · {brand or '전체 브랜드'} 기준 · {src}")

    master = S["master"]
    rate = get_rate()
    st.caption(f"💱 적용 환율: **{rate:,.1f}원/$** (당월 평균)")

    amz_ts = sales_timeseries(master, S["asales"], brand)
    tt_ts = sales_timeseries(master, S["tsales"], brand)
    amz_m = agg_period(amz_ts, "monthly")
    tt_m = agg_period(tt_ts, "monthly")

    def month_row(g, offset=0):
        """0=이번 달, 1=전월."""
        if g is None or g.empty:
            return None
        now = pd.Period(datetime.now(), freq="M") - offset
        hit = g[g["_p"] == now]
        return hit.iloc[0] if not hit.empty else None

    a_now, a_prev = month_row(amz_m, 0), month_row(amz_m, 1)
    t_now, t_prev = month_row(tt_m, 0), month_row(tt_m, 1)
    a_rev = float(a_now["revenue"]) if a_now is not None else 0.0
    a_pre = float(a_prev["revenue"]) if a_prev is not None else 0.0
    t_rev = float(t_now["revenue"]) if t_now is not None else 0.0
    t_pre = float(t_prev["revenue"]) if t_prev is not None else 0.0
    total, total_pre = a_rev + t_rev, a_pre + t_pre
    days_elapsed = max(datetime.now().day, 1)

    def mom(cur, prev):
        return f"{(cur - prev) / prev * 100:+.1f}%" if prev > 0 else None

    st.subheader(f"📅 {datetime.now().year}년 {datetime.now().month}월 통합 핵심 지표")
    c1a, c1b, c2a, c2b, c3a, c3b = st.columns([2.5, 1, 2.5, 1, 2.5, 1])
    metric_pair(c1a, c1b, "💰 통합 총 GMV", f"${total:,.2f}" if total else "-",
                delta=mom(total, total_pre), krw_usd=total, rate=rate,
                sub_label=f"일 평균 (1~{days_elapsed}일)",
                sub_value=f"${total / days_elapsed:,.2f}" if total else "-")
    metric_pair(c2a, c2b, "📦 Amazon GMV", f"${a_rev:,.2f}" if a_rev else "-",
                delta=mom(a_rev, a_pre), krw_usd=a_rev, rate=rate,
                sub_label="일 평균", sub_value=f"${a_rev / days_elapsed:,.2f}" if a_rev else "-",
                note=f"{total and a_rev / total * 100:.0f}% 비중" if total else None)
    metric_pair(c3a, c3b, "🛍️ TikTok GMV", f"${t_rev:,.2f}" if t_rev else "-",
                delta=mom(t_rev, t_pre), krw_usd=t_rev, rate=rate,
                sub_label="일 평균", sub_value=f"${t_rev / days_elapsed:,.2f}" if t_rev else "-",
                note=f"{total and t_rev / total * 100:.0f}% 비중" if total else None)

    ad_month = ads_by_period(S["ads"], "monthly", brand or None)
    cur_label = f"{datetime.now().year}년 {datetime.now().month}월"
    spend = ad_month.get(cur_label, {}).get("spend", 0.0)
    tacos = (spend / total * 100) if total and spend else None
    a_units = float(a_now["units"]) if a_now is not None else 0.0
    t_units = float(t_now["units"]) if t_now is not None else 0.0

    c4a, c4b, c5a, c5b, c6a, c6b = st.columns([2.5, 1, 2.5, 1, 2.5, 1])
    metric_pair(c4a, c4b, "📢 TACOS", f"{tacos:.2f}%" if tacos else "-",
                help="TACOS = 총 광고비 ÷ 통합 총 GMV × 100")
    metric_pair(c5a, c5b, "💸 총 광고비", f"${spend:,.2f}" if spend else "-",
                krw_usd=spend, rate=rate,
                help="캠페인 단위 광고비 합계 (사이드바 업로드 또는 시트 광고 탭)")
    metric_pair(c6a, c6b, "🧾 통합 판매량", fmt(a_units + t_units),
                sub_label="Amazon / TikTok",
                sub_value=f"{fmt(a_units)} / {fmt(t_units)}")

    # ============ 재고 현황 ============
    st.divider()
    st.subheader("📦 재고 현황")
    amz = apply_filters(S["amazon"], brand, "")
    tt = apply_filters(S["tiktok"], brand, "")
    po = apply_filters(S["po"], brand, "")
    tr = apply_filters(S["tr"], brand, "")

    def col_sum(df, c):
        return ifloor(df[c].sum()) if (df is not None and not df.empty and c in df.columns) else 0

    amz_inv = col_sum(amz, "Total Inventory")
    cc_inv = col_sum(amz, "CCONMA Inventory")
    fba_inv = col_sum(amz, "Total FBA Inventory")
    tt_inv = col_sum(tt, "Total")
    crit = int((amz["Status"] == "Critical").sum()) if (amz is not None and not amz.empty) else 0
    warn = int((amz["Status"] == "Warning").sum()) if (amz is not None and not amz.empty) else 0
    heal = int((amz["Status"] == "Healthy").sum()) if (amz is not None and not amz.empty) else 0
    daily_avg = amz["DailyAvg"].sum() if (amz is not None and "DailyAvg" in amz.columns) else 0
    avg_cov = (amz_inv / daily_avg) if daily_avg > 0 else None
    inv_value = 0.0
    if amz is not None and not amz.empty:
        price_map = {r["SKU"]: r["price"] for _, r in master.iterrows()}
        inv_value = sum(price_map.get(r["SKU"], 0.0) * r["Total Inventory"] for _, r in amz.iterrows())

    i1a, i1b, i2a, i2b, i3a, i3b = st.columns([2.5, 1, 2.5, 1, 2.5, 1])
    metric_pair(i1a, i1b, "📦 Amazon 총 재고", fmt(amz_inv),
                sub_label="CCONMA / FBA", sub_value=f"{fmt(cc_inv)} / {fmt(fba_inv)}")
    metric_pair(i2a, i2b, "🛍️ TikTok 총 재고", fmt(tt_inv),
                sub_label="CCONMA + FBT", sub_value="-" if not tt_inv else fmt(tt_inv))
    metric_pair(i3a, i3b, "⏳ 평균 재고 회전일",
                f"{avg_cov:,.0f}일" if avg_cov else "-",
                krw_usd=inv_value, rate=rate,
                sub_label="재고 자산 (판매가 기준)",
                sub_value=usd(inv_value) if inv_value else "-")

    i4a, i4b, i5a, i5b, i6a, i6b = st.columns([2.5, 1, 2.5, 1, 2.5, 1])
    metric_pair(i4a, i4b, "🚨 Critical SKU", fmt(crit),
                sub_label="Warning / Healthy", sub_value=f"{fmt(warn)} / {fmt(heal)}")
    metric_pair(i5a, i5b, "🧾 발주 필요 SKU", fmt(len(po) if po is not None else 0),
                sub_label="기준", sub_value=f"Coverage < {PO_THRESHOLD}일")
    metric_pair(i6a, i6b, "🚚 SO 필요 SKU", fmt(len(tr) if tr is not None else 0),
                sub_label="기준", sub_value=f"FBA Cov < {TR_FBA_DAYS}일")

    s1, s2 = st.columns([1, 1.6])
    with s1:
        if crit + warn + heal:
            fig = go.Figure(go.Bar(
                x=[crit, warn, heal], y=["Critical", "Warning", "Healthy"], orientation="h",
                marker_color=[COLORS["crit"], COLORS["warn"], COLORS["heal"]],
                text=[crit, warn, heal], textposition="outside"))
            fig.update_layout(title="재고 상태 분포", height=260,
                              margin=dict(l=10, r=10, t=40, b=10),
                              yaxis=dict(autorange="reversed"),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, key="home_status_dist")
    with s2:
        if amz is not None and not amz.empty:
            bs = amz.groupby("Brand").agg(
                SKU=("SKU", "count"),
                재고=("Total Inventory", "sum"),
                Critical=("Status", lambda s: int((s == "Critical").sum())),
            ).reset_index().sort_values("재고", ascending=False)
            bs["재고"] = bs["재고"].apply(fmt)
            st.markdown("**브랜드별 재고 요약**")
            st.dataframe(bs, use_container_width=True, hide_index=True, height=220)

    if amz is not None and not amz.empty and crit:
        with st.expander(f"🚨 긴급 재고 — Critical {crit}건 (회전일 짧은 순)", expanded=False):
            urg = amz[amz["Status"] == "Critical"].sort_values("CoverageDays").head(15)
            st.dataframe(urg[["Brand", "SKU", "Product Name", "Total Inventory",
                              "DailyAvg", "CoverageDays"]],
                         use_container_width=True, hide_index=True)

    # ============ 월별 통합 매출 추이 ============
    st.divider()
    st.subheader("📈 월별 통합 매출 추이")
    labels = []
    for g in (amz_m, tt_m):
        if g is not None and not g.empty:
            labels += list(zip(g["_p"].tolist(), g["기간"].tolist()))
    labels = [lbl for _, lbl in sorted(set(labels), key=lambda x: x[0])]

    if not labels:
        st.info("판매 데이터가 없습니다. 사이드바에서 데모를 켜거나 시트를 연동하세요.")
    else:
        a_map = dict(zip(amz_m["기간"], amz_m["revenue"])) if not amz_m.empty else {}
        t_map = dict(zip(tt_m["기간"], tt_m["revenue"])) if not tt_m.empty else {}
        a_vals = [a_map.get(m, 0) for m in labels]
        t_vals = [t_map.get(m, 0) for m in labels]
        c_vals = [a + t for a, t in zip(a_vals, t_vals)]

        fig = go.Figure()
        fig.add_bar(x=labels, y=a_vals, name="Amazon GMV", marker_color=COLORS["amz"])
        fig.add_bar(x=labels, y=t_vals, name="TikTok GMV", marker_color=COLORS["tt"])
        fig.add_scatter(x=labels, y=c_vals, name="통합 GMV", mode="lines+markers",
                        line=dict(color="#22c55e", width=2.5), marker=dict(size=8))
        fig.update_layout(barmode="group", height=400,
                          xaxis={"categoryorder": "array", "categoryarray": labels},
                          yaxis_tickprefix="$", yaxis_tickformat=",.0f",
                          margin=dict(l=0, r=0, t=20, b=0),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True, key="home_monthly_trend")

        d_map = dict(zip(amz_m["기간"], amz_m["days"])) if not amz_m.empty else {}
        d_map.update(dict(zip(tt_m["기간"], tt_m["days"])) if not tt_m.empty else {})
        disp = pd.DataFrame({
            "월": labels,
            "통합 GMV": [usd(v) if v else "-" for v in c_vals],
            "일 평균": [usd(c_vals[i] / d_map.get(m, 1)) if c_vals[i] else "-"
                     for i, m in enumerate(labels)],
            "원화 환산": [krw_short(v, rate) or "-" for v in c_vals],
            "Amazon GMV": [usd(v) if v else "-" for v in a_vals],
            "TikTok GMV": [usd(v) if v else "-" for v in t_vals],
            "MoM": ["-"] + [f"{(c_vals[i] - c_vals[i-1]) / c_vals[i-1] * 100:+.1f}%"
                            if c_vals[i-1] > 0 else "-" for i in range(1, len(c_vals))],
        })
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # ============ 브랜드 요약 + 메뉴 ============
    st.divider()
    roll = brand_rollup(master, S["amazon"], S["tiktok"], S["asales"], S["tsales"], S["ads"])
    if not roll.empty:
        st.subheader("🏷 브랜드별 요약 (최근 30일)")
        bsum = roll[["Brand", "SKU 수", "총 매출 (30D)", "광고비 (30D)", "총 재고", "Critical SKU"]].copy()
        bsum["총 매출 (30D)"] = bsum["총 매출 (30D)"].apply(usd)
        bsum["광고비 (30D)"] = bsum["광고비 (30D)"].apply(lambda v: usd(v) if v else "-")
        bsum["총 재고"] = bsum["총 재고"].apply(fmt)
        st.dataframe(bsum, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("바로가기")
    cols = st.columns(3)
    menus = [("🏷 Brand", "Brand"), ("📦 Amazon Inventory", "Amazon Inventory"),
             ("📋 Inventory Planning", "Inventory Planning"),
             ("🎵 TikTok Inventory", "TikTok Inventory"), ("📈 Sales", "Sales"),
             ("⚙️ Settings", "Settings")]
    for i, (label, target) in enumerate(menus):
        with cols[i % 3]:
            if st.button(label, use_container_width=True, key=f"nav_{target}"):
                st.session_state["menu"] = target
                st.rerun()


def page_amazon_inventory(S, brand):
    st.title("Amazon Inventory")
    st.caption("CCONMA + FBA(Available / Inbound / Reserved 분리) · Coverage / Status")

    df = apply_filters(S["amazon"], brand, st.session_state.get("query", ""), use_status=False)

    # ---- 상단 KPI (정수/절삭, 브랜드 필터 적용) ----
    def col_sum(name):
        return df[name].sum() if (df is not None and not df.empty and name in df.columns) else 0
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Available Inventory", fmt(col_sum("FBA Available")))
    k2.metric("Inbound Inventory", fmt(col_sum("FBA Inbound")))
    k3.metric("Reserved Inventory", fmt(col_sum("FBA Reserved")))
    k4.metric("Total FBA Inventory", fmt(col_sum("Total FBA Inventory")))
    k5.metric("Total CCONMA Inventory", fmt(col_sum("CCONMA Inventory")))
    k6.metric("Total Inventory", fmt(col_sum("Total Inventory")))

    f1, f2 = st.columns(2)
    fs = f1.selectbox("Status", ["전체", "Critical", "Warning", "Healthy"], key="amz_status")
    fc = f2.selectbox("Coverage", ["전체", "< 30일", "30–60일", "> 60일"], key="amz_cov")
    df = apply_filters(S["amazon"], brand, st.session_state.get("query", ""),
                       use_status=True, fs=fs, fc=fc)
    st.caption(f"{len(df)} / {len(S['amazon'])} SKU")
    cols_order = ["Brand", "Internal Code", "SKU", "ASIN", "Product Name", "CCONMA Inventory",
                  "FBA Available", "FBA Inbound", "FBA Reserved",
                  "Total FBA Inventory", "Total Inventory", "CoverageDays", "Status"]
    qty_cols = ["CCONMA Inventory", "FBA Available", "FBA Inbound", "FBA Reserved",
                "FBA Reserved Orders", "Total FBA Inventory", "Total Inventory"]
    if not df.empty:
        df = df[[c for c in cols_order if c in df.columns]].copy()
        for c in qty_cols:
            if c in df.columns:
                df[c] = df[c].apply(ifloor)
        df = df.rename(columns={"CoverageDays": "Coverage Days"})
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
    fs = f1.selectbox("Status", ["전체", "Critical", "Warning", "Healthy"], key="tt_status")
    fc = f2.selectbox("Coverage", ["전체", "< 30일", "30–60일", "> 60일"], key="tt_cov")
    df = apply_filters(S["tiktok"], brand, st.session_state.get("query", ""),
                       use_status=True, fs=fs, fc=fc)
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


def page_brand(S, brand):
    st.title("Brand Performance")
    st.caption("Internal Code 접두어 기준 브랜드 귀속 · 매출 · 판매량 · 광고비")

    master = S["master"]
    ads = S["ads"]
    roll = brand_rollup(master, S["amazon"], S["tiktok"], S["asales"], S["tsales"], ads)
    if roll.empty:
        st.info("브랜드 데이터가 없습니다.")
        return

    view = roll[roll["Brand"] == brand] if brand else roll

    # ---- 브랜드 카드 ----
    cards = view.head(5)
    cols = st.columns(len(cards)) if len(cards) else [st]
    for col, (_, r) in zip(cols, cards.iterrows()):
        with col:
            st.markdown(f"**{r['Brand']}**")
            st.metric("총 매출 (30D)", usd(r["총 매출 (30D)"]), f"{fmt(r['SKU 수'])} SKU")
            st.caption(f"판매량 {fmt(r['Amazon 판매량 (30D)'] + r['TikTok 판매량 (30D)'])} · "
                       f"광고비 {usd(r['광고비 (30D)'])}")

    st.divider()
    st.subheader("브랜드별 통합 성과")
    show = view.copy()
    for c in ["Amazon 매출 (30D)", "TikTok 매출 (30D)", "총 매출 (30D)", "광고비 (30D)", "광고매출 (30D)"]:
        show[c] = show[c].apply(usd)
    for c in ["ACOS", "광고비 비중"]:
        show[c] = show[c].apply(lambda v: f"{v}%" if v is not None and v == v else "-")
    st.dataframe(show, use_container_width=True)
    download_btn(roll, "⬇ 브랜드 성과 CSV", "brand_performance.csv")

    # ---- 매출 / 판매량 비교 ----
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        bar = view[["Brand", "Amazon 매출 (30D)", "TikTok 매출 (30D)"]].melt(
            id_vars="Brand", var_name="채널", value_name="매출")
        fig = px.bar(bar, x="Brand", y="매출", color="채널", barmode="group",
                     title="브랜드별 채널 매출 · 30d",
                     color_discrete_sequence=[COLORS["amz"], COLORS["tt"]])
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True, key="brand_channel_bar")
    with c2:
        bd = brand_daily(master, S["asales"])
        if brand and not bd.empty:
            bd = bd[bd["Brand"] == brand]
        if bd.empty:
            st.info("일별 데이터 없음")
        else:
            fig = px.line(bd, x="date", y="revenue", color="Brand",
                          title="브랜드별 일별 매출 추이 · 30d",
                          color_discrete_map=BRAND_COLORS)
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True, key="brand_daily_line")

    # ---- 광고비 ----
    st.divider()
    st.subheader("광고비 (캠페인 단위)")
    st.caption(f"데이터 소스: {S['ads_src']} · 캠페인명에 브랜드 키워드가 있으면 자동으로 브랜드에 귀속됩니다")
    if ads is None or ads.empty:
        st.info("광고비 데이터가 아직 없습니다. 사이드바에서 CSV/XLSX를 올리거나, "
                "연동된 구글 시트에 '광고' 또는 'Campaign'이 들어간 탭을 추가하면 자동으로 읽습니다.")
        with st.expander("필요한 컬럼 양식 보기"):
            st.markdown(
                "| 컬럼 | 필수 | 인식되는 이름 |\n|---|---|---|\n"
                "| 날짜 | 권장 | Date · 날짜 · 일자 |\n"
                "| 캠페인명 | **필수** | Campaign Name · Campaign · 캠페인 |\n"
                "| 광고비 | **필수** | Spend · Cost · 광고비 · 비용 |\n"
                "| 노출수 | 선택 | Impressions · 노출수 |\n"
                "| 클릭수 | 선택 | Clicks · 클릭수 |\n"
                "| 주문수 | 선택 | Orders · 주문수 |\n"
                "| 광고매출 | 선택 | 7 Day Total Sales · 광고매출 |\n\n"
                "캠페인명 안에 `NOONI` · `IDC` / `I DEW CARE` · `IMM` / `I'M MEME` · `KAJA` 중 "
                "하나가 들어 있으면 해당 브랜드로 자동 집계됩니다. "
                "Brand 컬럼이 따로 있으면 그 값을 우선합니다.")
    else:
        ab = ads_by_brand(ads)
        if brand:
            ab = ab[ab["Brand"] == brand]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 광고비", usd(ab["Spend"].sum()))
        m2.metric("광고매출", usd(ab["Ad Sales"].sum()))
        tot_spend, tot_as = ab["Spend"].sum(), ab["Ad Sales"].sum()
        m3.metric("ACOS", f"{tot_spend / tot_as * 100:.1f}%" if tot_as else "-")
        m4.metric("캠페인 수", fmt(ab["Campaigns"].sum()))
        cc1, cc2 = st.columns(2)
        with cc1:
            hbar(ab.sort_values("Spend", ascending=False), "Spend", "Brand",
                 "브랜드별 광고비", COLORS["accent"], key="brand_ad_spend")
        with cc2:
            camp = ads.groupby(["Campaign", "Brand"], dropna=False)["Spend"].sum().reset_index()
            if brand:
                camp = camp[camp["Brand"] == brand]
            camp = camp.sort_values("Spend", ascending=False).head(10)
            hbar(camp, "Spend", "Campaign", "캠페인 광고비 Top 10", COLORS["amz"],
                 key="brand_campaign_top")
        st.markdown("##### 캠페인 상세")
        st.dataframe(ads.sort_values("Spend", ascending=False), use_container_width=True, height=320)
        download_btn(ads, "⬇ 광고비 CSV", "ad_spend.csv")

    # ---- 브랜드 내 SKU ----
    st.divider()
    st.subheader("브랜드 내 SKU 매출 Top 10")
    t1, t2 = st.tabs(["Amazon", "TikTok Shop"])
    with t1:
        hbar(sku_revenue_table(master, S["asales"], brand).head(10),
             "30D Revenue", "Product Name", "Amazon · 30d", COLORS["amz"],
             key="brand_sku_amz")
    with t2:
        hbar(sku_revenue_table(master, S["tsales"], brand).head(10),
             "30D Revenue", "Product Name", "TikTok Shop · 30d", COLORS["tt"],
             key="brand_sku_tt")

    # ---- 미분류 경고 ----
    unassigned = master[master["Brand"] == BRAND_UNASSIGNED] if "Brand" in master.columns else pd.DataFrame()
    if not unassigned.empty:
        st.divider()
        st.warning(f"브랜드 판정 실패 {len(unassigned)} SKU — Internal Code 접두어를 확인하세요. "
                   "상세는 Settings 페이지에 있습니다.")


def page_settings(S, brand):
    st.title("Settings")
    sheet = S["sheet"]
    cc_idx = S["cc_idx"]
    val = S["validation"]

    st.subheader("Data Validation")
    if sheet["configured"]:
        conn = "✅ 연결됨 (Google Sheets)"
    elif sheet["error"]:
        conn = f"❌ 연결 안 됨 — {sheet['error']}"
    else:
        conn = "⚠️ 데모 / 업로드 모드"
    last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if sheet["configured"] else "-"
    detected = ", ".join(f"{k}={v}" for k, v in sheet.get("detected", {}).items()) or "-"

    c1, c2, c3 = st.columns(3)
    c1.metric("Google Sheets 연결 상태", "연결됨" if sheet["configured"] else ("오류" if sheet["error"] else "데모"))
    c2.metric("CCONMA 총 재고 수량", fmt(val["cc_total"]))
    c3.metric("총 행 수 (CCONMA)", fmt(cc_idx.get("n_rows", 0)))
    c4, c5, c6 = st.columns(3)
    c4.metric("매칭 성공 SKU 수", fmt(val["matched"]))
    c5.metric("매칭 실패 SKU 수", fmt(val["failed"]))
    c6.metric("선택된 CCONMA 컬럼", str(cc_idx.get("col") or "-"))

    info_rows = [
        ("연결 상태", conn),
        ("마지막 동기화 시간", last_sync),
        ("읽어온 시트명", detected),
        ("총 행 수 (CCONMA 시트)", str(cc_idx.get("n_rows", 0))),
        ("실제 선택된 CCONMA 컬럼명", str(cc_idx.get("col") or "-")),
        ("CCONMA 컬럼 인식 방식", str(cc_idx.get("col_method", "-"))),
        ("CCONMA 총 재고 수량", fmt(val["cc_total"])),
        ("매칭 성공 SKU 수", str(val["matched"])),
        ("매칭 실패 SKU 수", str(val["failed"])),
        ("인식된 컬럼 목록", ", ".join(cc_idx.get("columns", [])) or "-"),
    ]
    st.table(pd.DataFrame(info_rows, columns=["항목", "값"]))

    st.subheader("매칭 실패 SKU")
    st.caption("CCONMA 시트에는 있으나 Internal Code · SKU · ASIN 어느 것으로도 마스터와 매칭되지 않은 행")
    fr = val["failed_rows"]
    if fr is not None and not fr.empty:
        st.dataframe(fr, use_container_width=True, height=360)
        download_btn(fr, "⬇ 실패 SKU CSV", "cconma_unmatched.csv")
    else:
        st.success("매칭 실패 행 없음 (또는 데모 모드)")

    # ---- 브랜드 매핑 검증 ----
    st.divider()
    st.subheader("브랜드 매핑 검증")
    st.caption("PRODUCT INFO F열 Internal Code 접두어 기준 · NOONI / IDC / IMM / KAJA")
    master = S["master"]
    if "Brand" in master.columns:
        cnt = master.groupby(["Brand", "Brand Source"]).size().reset_index(name="SKU 수")
        b1, b2 = st.columns([1, 1])
        with b1:
            st.markdown("**브랜드별 SKU 수**")
            st.dataframe(master.groupby("Brand").size().reset_index(name="SKU 수"),
                         use_container_width=True, hide_index=True)
        with b2:
            st.markdown("**판정 근거별 분포**")
            st.dataframe(cnt, use_container_width=True, hide_index=True)

        un = master[master["Brand"] == BRAND_UNASSIGNED]
        st.markdown("**브랜드 판정 실패 SKU**")
        if un.empty:
            st.success("모든 SKU가 4개 브랜드에 귀속되었습니다")
        else:
            show = un[["SKU", "Internal Code", "Brand Raw", "Product Name"]]
            st.dataframe(show, use_container_width=True, height=280)
            download_btn(show, "⬇ 미분류 SKU CSV", "brand_unassigned.csv")

        weak = master[master["Brand Source"].isin(["제품명 추정", "SKU 추정"])]
        if not weak.empty:
            with st.expander(f"Internal Code 없이 추정으로 판정된 SKU {len(weak)}건"):
                st.dataframe(weak[["SKU", "Internal Code", "Brand", "Brand Source", "Product Name"]],
                             use_container_width=True, height=240)

    st.divider()
    st.subheader("연동 가이드")
    st.markdown(
        "- 환경변수: `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`(원문/base64) 또는 `GOOGLE_API_KEY`\n"
        "- CCONMA 컬럼 인식: ①이름 'CCONMA' ②이름에 'CCONMA' 포함 ③M열\n"
        "- 재고 매칭 우선순위: ①Internal Code ②SKU(SAP CODE) ③ASIN\n"
        "- 브랜드 판정 우선순위: ①Internal Code 접두어 ②Brand Name 컬럼 ③제품명 ④SKU\n"
        "- 광고비 탭 인식: 시트명에 '광고' · 'Campaign' · 'Advertising' 포함")


def render_period_view(S, brand, sales, channel, period, color):
    """ELROEL 스타일 월별/주별 뷰: 브랜드 비교 차트 + 핵심 지표 테이블 + 광고 추이."""
    master = S["master"]
    rate = get_rate()
    unit = "월" if period == "monthly" else "주"
    delta_label = "MoM (%)" if period == "monthly" else "WoW (%)"

    ts = sales_timeseries(master, sales, brand)
    g = agg_period(ts, period)
    if g.empty:
        st.info("판매 데이터가 없습니다.")
        return
    labels = g["기간"].tolist()

    st.subheader(f"{unit}별 GMV")
    bm = brand_period_matrix(master, sales, period, brand or None)
    fig = go.Figure()
    if not bm.empty and not brand:
        for b in brand_options(master):
            sub = bm[bm["Brand"] == b]
            if sub.empty:
                continue
            vals = dict(zip(sub["기간"], sub["revenue"]))
            fig.add_bar(x=labels, y=[vals.get(m, 0) for m in labels], name=b,
                        marker_color=BRAND_COLORS.get(b, COLORS["accent"]))
        fig.add_scatter(x=labels, y=g["revenue"].tolist(), name="합산",
                        mode="lines+markers", line=dict(color="#22c55e", width=2, dash="dot"),
                        marker=dict(size=8))
        fig.update_layout(barmode="group")
    else:
        fig.add_bar(x=labels, y=g["revenue"].tolist(), name=brand or channel,
                    marker_color=color,
                    text=[f"${v:,.0f}" for v in g["revenue"]], textposition="outside")
    fig.update_layout(height=420, xaxis={"categoryorder": "array", "categoryarray": labels},
                      yaxis_tickprefix="$", yaxis_tickformat=",.0f",
                      margin=dict(l=0, r=0, t=20, b=0),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, key=f"gmv_{channel}_{period}")
    if not brand:
        st.caption("💡 막대 = 브랜드별 GMV · 점선 = 전체 합산")

    st.divider()
    st.subheader(f"📋 {unit}별 핵심 지표")
    adp = ads_by_period(S["ads"], period, brand or None)
    disp = pd.DataFrame({
        unit: labels,
        "GMV": [usd(v) for v in g["revenue"]],
        "일 평균": [usd(v) if v == v and v else "-" for v in g["일 평균"]],
        "원화 환산": [krw_short(v, rate) or "-" for v in g["revenue"]],
        delta_label: [f"{v:+.1f}%" if v == v else "-" for v in g["변화율"]],
        "판매 수량": [fmt(v) for v in g["units"]],
        "객단가": [usd(r / u) if u else "-" for r, u in zip(g["revenue"], g["units"])],
    })
    has_ad = any(m in adp for m in labels)
    if has_ad:
        spends = [adp.get(m, {}).get("spend", 0.0) for m in labels]
        adsales = [adp.get(m, {}).get("adsales", 0.0) for m in labels]
        disp["광고비"] = [usd(v) if v else "-" for v in spends]
        disp["광고매출"] = [usd(v) if v else "-" for v in adsales]
        disp["ACOS (%)"] = [f"{s / a * 100:.2f}%" if a else "-" for s, a in zip(spends, adsales)]
        disp["TACOS (%)"] = [f"{s / r * 100:.2f}%" if (r and s) else "-"
                             for s, r in zip(spends, g["revenue"])]
    st.dataframe(disp, use_container_width=True, hide_index=True)
    download_btn(g[["기간", "revenue", "units", "일 평균", "변화율"]],
                 f"⬇ {unit}별 지표 CSV", f"{channel}_{period}_{brand or 'all'}.csv")

    if has_ad:
        st.divider()
        st.subheader("📢 광고비 추이")
        fa = go.Figure()
        fa.add_bar(x=labels, y=[adp.get(m, {}).get("spend", 0.0) for m in labels],
                   name="광고비", marker_color=COLORS["accent"])
        fa.add_scatter(x=labels, y=[adp.get(m, {}).get("adsales", 0.0) for m in labels],
                       name="광고매출", mode="lines+markers",
                       line=dict(color="#22c55e", width=2, dash="dot"))
        fa.update_layout(height=340, yaxis_tickprefix="$", yaxis_tickformat=",.0f",
                         margin=dict(l=0, r=0, t=20, b=0),
                         legend=dict(orientation="h", yanchor="bottom", y=1.02),
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fa, use_container_width=True, key=f"ad_{channel}_{period}")
    else:
        st.caption("💡 광고비 데이터를 올리면 ACOS · TACOS · 광고비 추이가 함께 표시됩니다.")


def render_detail_view(S, brand, sales, channel, color):
    """ELROEL 상세 탭: 일별 추이 + 제품×기간 피벗 + 제품별 합계."""
    master = S["master"]
    ts = sales_timeseries(master, sales, brand)
    if ts.empty:
        st.info("판매 데이터가 없습니다.")
        return

    months = sorted({d.strftime("%Y-%m") for d in ts["date"]}, reverse=True)
    sel = st.selectbox("기간 선택", ["전체"] + months, key=f"detail_{channel}")
    view = ts if sel == "전체" else ts[ts["date"].dt.strftime("%Y-%m") == sel]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 GMV", usd(view["revenue"].sum()))
    k2.metric("총 판매량", fmt(view["units"].sum()))
    k3.metric("일 평균 GMV", usd(view["revenue"].mean()) if len(view) else "-")
    k4.metric("집계 일수", f"{len(view)}일")

    st.subheader("📈 일별 GMV 추이")
    fig = px.bar(view.sort_values("date"), x="date", y="revenue",
                 labels={"revenue": "GMV ($)", "date": "날짜"},
                 color_discrete_sequence=[color])
    fig.update_layout(height=360, xaxis_tickangle=-45, yaxis_tickprefix="$",
                      yaxis_tickformat=",.0f", margin=dict(l=0, r=0, t=20, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, key=f"daily_{channel}")

    st.divider()
    st.subheader("🛍️ 제품별 기간 매출")
    cc1, cc2 = st.columns(2)
    p_period = cc1.radio("집계 단위", ["월별", "주별"], horizontal=True, key=f"pp_{channel}")
    p_metric = cc2.radio("지표", ["매출", "판매량"], horizontal=True, key=f"pm_{channel}")
    piv = product_period_pivot(master, sales,
                               "monthly" if p_period == "월별" else "weekly",
                               brand or None,
                               "revenue" if p_metric == "매출" else "units")
    if piv is None or piv.empty:
        st.info("집계할 제품 데이터가 없습니다.")
    else:
        st.caption(f"상위 {len(piv) - 1}개 제품 · 좌측 2개 열 고정 · 가로 스크롤")
        render_frozen_table(piv, frozen_cols=2, height=460,
                            is_currency=(p_metric == "매출"))
        download_btn(piv, "⬇ 제품별 피벗 CSV", f"{channel}_product_pivot.csv")

    st.divider()
    st.subheader("🏆 제품별 합계 (최근 30일)")
    full = sku_revenue_table(master, sales, brand)
    if full.empty:
        st.info("판매 데이터 없음")
        return
    total_rev = full["30D Revenue"].sum()
    show = full.copy()
    show["매출 비중"] = (show["30D Revenue"] / total_rev * 100).round(1).astype(str) + "%"
    show["30D Revenue"] = show["30D Revenue"].apply(usd)
    show["30D Units"] = show["30D Units"].apply(fmt)
    st.dataframe(show, use_container_width=True, height=360, hide_index=True)
    download_btn(full, "⬇ SKU 매출 CSV", f"{channel}_sku_sales_{brand or 'all'}.csv")
    hbar(full.head(15), "30D Revenue", "Product Name", "매출 Top 15 · 30d", color,
         key=f"top15_{channel}")


def page_sales(S, brand):
    st.title("📈 Sales Dashboard")
    st.caption(f"Amazon + TikTok Shop 판매 분석 · {brand or '전체 브랜드'} 기준")
    master = S["master"]

    tabs = st.tabs(["🛒 Amazon 월별", "📦 Amazon 주별", "🔍 Amazon 상세",
                    "📅 TikTok 월별", "📆 TikTok 주별", "📋 TikTok 상세"])

    with tabs[0]:
        render_period_view(S, brand, S["asales"], "amazon", "monthly", COLORS["amz"])
    with tabs[1]:
        render_period_view(S, brand, S["asales"], "amazon", "weekly", COLORS["amz"])
    with tabs[2]:
        agg = sales_aggregate(master, S["asales"], brand)
        kpi_row(agg)
        st.markdown("##### 브랜드 특화 KPI")
        k1, k2 = st.columns(2)
        k1.metric("NOONI Lip Oil 매출 (30D)",
                  usd(keyword_revenue(master, S["asales"], "NOONI", "lip oil")))
        k2.metric("I DEW CARE Tap Secret 매출 (30D)",
                  usd(keyword_revenue(master, S["asales"], "I DEW CARE", "tap secret")))
        st.divider()
        render_detail_view(S, brand, S["asales"], "amazon", COLORS["amz"])

    with tabs[3]:
        render_period_view(S, brand, S["tsales"], "tiktok", "monthly", COLORS["tt"])
    with tabs[4]:
        render_period_view(S, brand, S["tsales"], "tiktok", "weekly", COLORS["tt"])
    with tabs[5]:
        kpi_row(sales_aggregate(master, S["tsales"], brand))
        st.divider()
        render_detail_view(S, brand, S["tsales"], "tiktok", COLORS["tt"])


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
        menu_items = ["Home", "Brand", "Amazon Inventory", "Inventory Planning",
                      "TikTok Inventory", "Sales", "Settings"]
        st.session_state["menu"] = st.radio("메뉴", menu_items,
                                            index=menu_items.index(st.session_state.get("menu", "Home")))
        st.divider()

    # load data (after demo toggle is known)
    S = get_state()

    with st.sidebar:
        brands = brand_options(S["master"])
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
        st.file_uploader("광고비 · 캠페인별 (CSV/XLSX)", type=["csv", "xlsx", "xls"], key="_ads_file",
                         on_change=lambda: st.session_state.update(up_ads=_read_upload(st.session_state.get("_ads_file"))))
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
    elif menu == "Brand":
        page_brand(S, brand)
    elif menu == "Amazon Inventory":
        page_amazon_inventory(S, brand)
    elif menu == "Inventory Planning":
        page_inventory_planning(S, brand)
    elif menu == "TikTok Inventory":
        page_tiktok_inventory(S, brand)
    elif menu == "Sales":
        page_sales(S, brand)
    elif menu == "Settings":
        page_settings(S, brand)


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
