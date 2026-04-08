"""Ø´Ø¨ÙƒØ© Ø±ØµØ¯ v5 â€” Ù†Ø³Ø®Ø© Ù†Ù‡Ø§Ø¦ÙŠØ© Ù…Ø¹ Ø«ÙŠÙ… Ø¨Ù†ÙŠ/Ø£Ø³ÙˆØ¯"""
from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
import sqlite3, json, re, time, random, os, asyncio, smtplib, hashlib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
import httpx, urllib3
urllib3.disable_warnings()

GMAIL_USER   = os.getenv("GMAIL_USER",   "mohamedelmontassir439@gmail.com")
GMAIL_PASS   = os.getenv("GMAIL_PASS",   "nvzdanptagoovjxr")
TELEGRAM_BOT = os.getenv("TELEGRAM_BOT", "7849539613:AAFZTtMNEo92UqE3OIcXPdX65OCm8DrvgAA")
ADMIN_PASS   = os.getenv("ADMIN_PASS",   "rassd2026")
DB_PATH      = os.getenv("DB_PATH",      "data/rassd.db")
BASE_URL     = "https://www.marchespublics.gov.ma"
SHOW_URL     = f"{BASE_URL}/bdc/entreprise/consultation/show/"
LIST_URL     = f"{BASE_URL}/bdc/entreprise/consultation/"

CANCEL_KEYWORDS = ["annulÃ©","annulation","infructueux","infructueuse","sans suite","rÃ©siliation","Ù…Ù„ØºÙ‰","Ø¥Ù„ØºØ§Ø¡"]
GOODS_DOMAINS   = ["Mobilier & Ã‰quipements","Alimentation","Transport","Ã‰quipements mÃ©dicaux","Informatique"]

SUPPLIERS = {
    "Mobilier & Ã‰quipements": [
        {"nom":"KITEA Maroc","ville":"Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ø¯Ù†","tel":"0801 000 444","site":"kitea.com","desc":"Ø£Ø«Ø§Ø« ÙˆÙ…Ø¹Ø¯Ø§Øª Ù…ÙƒØªØ¨ÙŠØ©"},
        {"nom":"Mobilia","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡ØŒ Ø§Ù„Ø±Ø¨Ø§Ø·","tel":"0522 340 000","site":"mobilia.ma","desc":"Ø£Ø«Ø§Ø« Ø¹ØµØ±ÙŠ"},
        {"nom":"Bureau VallÃ©e","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡ØŒ Ø§Ù„Ø±Ø¨Ø§Ø·","tel":"0522 394 545","site":"bureauvallee.ma","desc":"Ù„ÙˆØ§Ø²Ù… Ù…ÙƒØªØ¨ÙŠØ©"},
    ],
    "Alimentation": [
        {"nom":"Marjane Holding","ville":"Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ø¯Ù†","tel":"0522 570 000","site":"marjane.ma","desc":"ØªÙˆØ±ÙŠØ¯ Ù…ÙˆØ§Ø¯ ØºØ°Ø§Ø¦ÙŠØ©"},
        {"nom":"Metro Cash & Carry","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡ØŒ Ø§Ù„Ø±Ø¨Ø§Ø·ØŒ ÙØ§Ø³","tel":"0522 666 000","site":"metro.ma","desc":"Ø¨ÙŠØ¹ Ø¨Ø§Ù„Ø¬Ù…Ù„Ø©"},
        {"nom":"Label'Vie","ville":"Ø§Ù„Ø±Ø¨Ø§Ø·ØŒ Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡","tel":"0537 718 800","site":"labelvie.ma","desc":"ØªÙˆØ±ÙŠØ¯ ØºØ°Ø§Ø¦ÙŠ"},
    ],
    "Transport": [
        {"nom":"Toyota Maroc","ville":"Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ø¯Ù†","tel":"0522 548 800","site":"toyota.ma","desc":"Ø³ÙŠØ§Ø±Ø§Øª ÙˆÙ…Ø±ÙƒØ¨Ø§Øª"},
        {"nom":"Iveco Maroc","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡","tel":"0522 351 900","site":"iveco.com","desc":"Ø´Ø§Ø­Ù†Ø§Øª ØªØ¬Ø§Ø±ÙŠØ©"},
        {"nom":"Peugeot CitroÃ«n Maroc","ville":"Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ø¯Ù†","tel":"0522 547 000","site":"psa-maroc.com","desc":"Ø³ÙŠØ§Ø±Ø§Øª ÙˆØ¹Ø±Ø¨Ø§Øª"},
    ],
    "Ã‰quipements mÃ©dicaux": [
        {"nom":"Pharma 5","ville":"Ø§Ù„Ø±Ø¨Ø§Ø·","tel":"0537 688 500","site":"pharma5.ma","desc":"Ù…Ø¹Ø¯Ø§Øª Ø·Ø¨ÙŠØ©"},
        {"nom":"Medimaroc","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡","tel":"0522 402 020","site":"medimaroc.ma","desc":"Ø£Ø¬Ù‡Ø²Ø© Ø·Ø¨ÙŠØ©"},
        {"nom":"Saidal Distribution","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡","tel":"0522 244 500","site":"saidal.ma","desc":"Ù…Ø³ØªÙ„Ø²Ù…Ø§Øª ØµØ­ÙŠØ©"},
    ],
    "Informatique": [
        {"nom":"Maghreb Systems","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡ØŒ Ø§Ù„Ø±Ø¨Ø§Ø·","tel":"0522 944 500","site":"maghrebsystems.com","desc":"Ø­Ù„ÙˆÙ„ ØªÙ‚Ù†ÙŠØ©"},
        {"nom":"Maroc Telecom Business","ville":"Ø¬Ù…ÙŠØ¹ Ø§Ù„Ù…Ø¯Ù†","tel":"0537 719 700","site":"iam.ma","desc":"Ø´Ø¨ÙƒØ§Øª ÙˆØ§ØªØµØ§Ù„Ø§Øª"},
        {"nom":"Dell Technologies Maroc","ville":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡","tel":"0522 958 000","site":"dell.com/ma","desc":"Ø£Ø¬Ù‡Ø²Ø© ÙˆØ®ÙˆØ§Ø¯Ù…"},
    ],
}

REGIONS = {
    "Tanger-TÃ©touan-Al HoceÃ¯ma": {"ar":"Ø·Ù†Ø¬Ø©-ØªØ·ÙˆØ§Ù†-Ø§Ù„Ø­Ø³ÙŠÙ…Ø©","villes":["TANGER","TETOUAN","AL HOCEIMA","LARACHE","CHEFCHAOUEN","MDIQ","FNIDEQ","OUEZZANE"]},
    "Oriental":                   {"ar":"Ø§Ù„Ø´Ø±Ù‚","villes":["OUJDA","NADOR","BERKANE","TAOURIRT","JERADA","DRIOUCH","GUERCIF"]},
    "FÃ¨s-MeknÃ¨s":                 {"ar":"ÙØ§Ø³-Ù…ÙƒÙ†Ø§Ø³","villes":["FES","MEKNES","TAZA","IFRANE","SEFROU","BOULEMANE","EL HAJEB"]},
    "Rabat-SalÃ©-KÃ©nitra":         {"ar":"Ø§Ù„Ø±Ø¨Ø§Ø·-Ø³Ù„Ø§-Ø§Ù„Ù‚Ù†ÙŠØ·Ø±Ø©","villes":["RABAT","SALE","KENITRA","KHEMISSET","SIDI KACEM","SIDI SLIMANE"]},
    "BÃ©ni Mellal-KhÃ©nifra":       {"ar":"Ø¨Ù†ÙŠ Ù…Ù„Ø§Ù„-Ø®Ù†ÙŠÙØ±Ø©","villes":["BENI MELLAL","KHOURIBGA","FQUIH BEN SALAH","AZILAL","MIDELT"]},
    "Casablanca-Settat":          {"ar":"Ø§Ù„Ø¯Ø§Ø± Ø§Ù„Ø¨ÙŠØ¶Ø§Ø¡-Ø³Ø·Ø§Øª","villes":["CASABLANCA","SETTAT","BERRECHID","EL JADIDA","MOHAMMEDIA","BENSLIMANE"]},
    "Marrakech-Safi":             {"ar":"Ù…Ø±Ø§ÙƒØ´-Ø¢Ø³ÙÙŠ","villes":["MARRAKECH","SAFI","ESSAOUIRA","EL KELAÃ‚ DES SRAGHNA","CHICHAOUA"]},
    "DrÃ¢a-Tafilalet":             {"ar":"Ø¯Ø±Ø¹Ø©-ØªØ§ÙÙŠÙ„Ø§Ù„Øª","villes":["ERRACHIDIA","OUARZAZATE","TINGHIR","ZAGORA"]},
    "Souss-Massa":                {"ar":"Ø³ÙˆØ³-Ù…Ø§Ø³Ø©","villes":["AGADIR","TIZNIT","TAROUDANT","INEZGANE","CHTOUKA AIT BAHA","TATA"]},
    "Guelmim-Oued Noun":          {"ar":"ÙƒÙ„Ù…ÙŠÙ…-ÙˆØ§Ø¯ Ù†ÙˆÙ†","villes":["GUELMIM","TAN-TAN","SIDI IFNI","ASSA"]},
    "LaÃ¢youne-Sakia El Hamra":    {"ar":"Ø§Ù„Ø¹ÙŠÙˆÙ†-Ø§Ù„Ø³Ø§Ù‚ÙŠØ© Ø§Ù„Ø­Ù…Ø±Ø§Ø¡","villes":["LAAYOUNE","BOUJDOUR","TARFAYA","ES-SEMARA"]},
    "Dakhla-Oued Ed-Dahab":       {"ar":"Ø§Ù„Ø¯Ø§Ø®Ù„Ø©-ÙˆØ§Ø¯ÙŠ Ø§Ù„Ø°Ù‡Ø¨","villes":["DAKHLA","AOUSSERD"]},
}

DOMAINS_FR = {
    "Travaux routiers":       ["voirie","route","piste","bitum","chaussÃ©e","autoroute","asphalte"],
    "Construction":           ["construction","bÃ¢timent","rÃ©habilitation","rÃ©novation","amÃ©nagement","gÃ©nie civil"],
    "Eau & Assainissement":   ["assainissement","eau potable","rÃ©seau","canalisation","hydraulique","forage","barrage"],
    "Ã‰lectricitÃ©":            ["Ã©lectricitÃ©","Ã©clairage","rÃ©seau Ã©lectrique","groupe Ã©lectrogÃ¨ne","Ã©nergie solaire"],
    "Informatique":           ["informatique","logiciel","systÃ¨me","serveur","rÃ©seau","numÃ©rique","application"],
    "Ã‰quipements mÃ©dicaux":   ["mÃ©dical","pharmaceutique","laboratoire","hospitalier","mÃ©dicament","santÃ©","clinique"],
    "Ã‰tudes & Conseil":       ["Ã©tude","ingÃ©nierie","architecture","topographie","audit","conseil","expertise"],
    "Nettoyage & SÃ©curitÃ©":   ["nettoyage","gardiennage","entretien","maintenance","sÃ©curitÃ©","surveillance"],
    "Mobilier & Ã‰quipements": ["mobilier","bureau","fourniture","Ã©quipement","matÃ©riel","outillage"],
    "Transport":              ["transport","vÃ©hicule","camion","bus","piÃ¨ces de rechange","carburant"],
    "Alimentation":           ["alimentaire","restauration","produit alimentaire","traiteur","catering"],
}
DOMAINS_AR = {
    # ØªØµÙ†ÙŠÙØ§Øª Ø±Ø³Ù…ÙŠØ©
    "Travaux":"Ø£Ø´ØºØ§Ù„","Fournitures":"ØªÙˆØ±ÙŠØ¯Ø§Øª","Services":"Ø®Ø¯Ù…Ø§Øª",
    "Travaux de bÃ¢timent":"Ø£Ø´ØºØ§Ù„ Ø§Ù„Ø¨Ù†Ø§Ø¡","Travaux routiers":"Ø£Ø´ØºØ§Ù„ Ø§Ù„Ø·Ø±Ù‚",
    "Travaux hydrauliques":"Ø£Ø´ØºØ§Ù„ Ù‡ÙŠØ¯Ø±ÙˆÙ„ÙŠÙƒÙŠØ©","Travaux d'assainissement":"Ø§Ù„ØµØ±Ù Ø§Ù„ØµØ­ÙŠ",
    "Travaux d'Ã©lectricitÃ©":"Ø£Ø´ØºØ§Ù„ Ø§Ù„ÙƒÙ‡Ø±Ø¨Ø§Ø¡","Travaux d'amÃ©nagement":"Ø£Ø´ØºØ§Ù„ Ø§Ù„ØªÙ‡ÙŠØ¦Ø©",
    "Travaux divers":"Ø£Ø´ØºØ§Ù„ Ù…ØªÙ†ÙˆØ¹Ø©",
    "Fournitures de bureau":"Ù„ÙˆØ§Ø²Ù… Ù…ÙƒØªØ¨ÙŠØ©","Fournitures informatiques":"Ù„ÙˆØ§Ø²Ù… Ù…Ø¹Ù„ÙˆÙ…Ø§ØªÙŠØ©",
    "Fournitures mÃ©dicales":"Ù„ÙˆØ§Ø²Ù… Ø·Ø¨ÙŠØ©","Fournitures alimentaires":"Ù„ÙˆØ§Ø²Ù… ØºØ°Ø§Ø¦ÙŠØ©",
    "MatÃ©riels et Ã©quipements":"Ù…Ø¹Ø¯Ø§Øª ÙˆØªØ¬Ù‡ÙŠØ²Ø§Øª",
    "VÃ©hicules et matÃ©riels roulants":"Ù…Ø±ÙƒØ¨Ø§Øª",
    "Services informatiques":"Ø®Ø¯Ù…Ø§Øª Ù…Ø¹Ù„ÙˆÙ…Ø§ØªÙŠØ©","Services de gardiennage":"Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø­Ø±Ø§Ø³Ø©",
    "Services de nettoyage":"Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ù†Ø¸Ø§ÙØ©","Services de transport":"Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ù†Ù‚Ù„",
    "Services de restauration":"Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø¥Ø·Ø¹Ø§Ù…","Prestations d'Ã©tudes":"Ø§Ù„Ø¯Ø±Ø§Ø³Ø§Øª",
    "Prestations d'audit":"Ø§Ù„ØªØ¯Ù‚ÙŠÙ‚","Prestations de formation":"Ø§Ù„ØªÙƒÙˆÙŠÙ†",
    "Prestations mÃ©dicales":"Ø§Ù„Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø·Ø¨ÙŠØ©","Services divers":"Ø®Ø¯Ù…Ø§Øª Ù…ØªÙ†ÙˆØ¹Ø©",
    # ØªØµÙ†ÙŠÙØ§Øª Ø§Ø­ØªÙŠØ§Ø·ÙŠØ©
    "Construction":"Ø§Ù„Ø¨Ù†Ø§Ø¡ ÙˆØ§Ù„ØªØ´ÙŠÙŠØ¯","Eau & Assainissement":"Ø§Ù„Ù…Ø§Ø¡ ÙˆØ§Ù„ØªØ·Ù‡ÙŠØ±",
    "Ã‰lectricitÃ©":"Ø§Ù„ÙƒÙ‡Ø±Ø¨Ø§Ø¡","Informatique":"Ø§Ù„Ù…Ø¹Ù„ÙˆÙ…ÙŠØ§Øª",
    "Ã‰quipements mÃ©dicaux":"Ø§Ù„Ù…Ø¹Ø¯Ø§Øª Ø§Ù„Ø·Ø¨ÙŠØ©","Ã‰tudes & Conseil":"Ø§Ù„Ø¯Ø±Ø§Ø³Ø§Øª",
    "Nettoyage & SÃ©curitÃ©":"Ø§Ù„Ù†Ø¸Ø§ÙØ© ÙˆØ§Ù„Ø­Ø±Ø§Ø³Ø©","Mobilier & Ã‰quipements":"Ø§Ù„Ø£Ø«Ø§Ø«",
    "Transport":"Ø§Ù„Ù†Ù‚Ù„","Alimentation":"Ø§Ù„Ø£ØºØ°ÙŠØ©","Autres services":"Ø®Ø¯Ù…Ø§Øª Ø£Ø®Ø±Ù‰",
}

# Ø§Ù„ØªØµÙ†ÙŠÙØ§Øª Ø§Ù„Ø±Ø³Ù…ÙŠØ© Ù„Ø¨ÙˆØ§Ø¨Ø© Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ© Ø§Ù„Ù…ØºØ±Ø¨ÙŠØ©
OFFICIAL_DOMAINS = {
    # Ø§Ù„Ø·Ø¨ÙŠØ¹Ø© Ø§Ù„Ø±Ø³Ù…ÙŠØ©
    "Travaux":        "Ø£Ø´ØºØ§Ù„",
    "Fournitures":    "ØªÙˆØ±ÙŠØ¯Ø§Øª",
    "Services":       "Ø®Ø¯Ù…Ø§Øª",
    # Ø§Ù„ÙØ¦Ø§Øª Ø§Ù„ØªÙØµÙŠÙ„ÙŠØ© Ø§Ù„Ø±Ø³Ù…ÙŠØ©
    "Travaux de bÃ¢timent":              "Ø£Ø´ØºØ§Ù„ Ø§Ù„Ø¨Ù†Ø§Ø¡",
    "Travaux routiers":                 "Ø£Ø´ØºØ§Ù„ Ø§Ù„Ø·Ø±Ù‚",
    "Travaux hydrauliques":             "Ø£Ø´ØºØ§Ù„ Ù‡ÙŠØ¯Ø±ÙˆÙ„ÙŠÙƒÙŠØ©",
    "Travaux d'assainissement":         "Ø£Ø´ØºØ§Ù„ Ø§Ù„ØµØ±Ù Ø§Ù„ØµØ­ÙŠ",
    "Travaux d'Ã©lectricitÃ©":            "Ø£Ø´ØºØ§Ù„ Ø§Ù„ÙƒÙ‡Ø±Ø¨Ø§Ø¡",
    "Travaux d'amÃ©nagement":            "Ø£Ø´ØºØ§Ù„ Ø§Ù„ØªÙ‡ÙŠØ¦Ø©",
    "Travaux divers":                   "Ø£Ø´ØºØ§Ù„ Ù…ØªÙ†ÙˆØ¹Ø©",
    "Fournitures de bureau":            "Ù„ÙˆØ§Ø²Ù… Ù…ÙƒØªØ¨ÙŠØ©",
    "Fournitures informatiques":        "Ù„ÙˆØ§Ø²Ù… Ù…Ø¹Ù„ÙˆÙ…Ø§ØªÙŠØ©",
    "Fournitures mÃ©dicales":            "Ù„ÙˆØ§Ø²Ù… Ø·Ø¨ÙŠØ©",
    "Fournitures alimentaires":         "Ù„ÙˆØ§Ø²Ù… ØºØ°Ø§Ø¦ÙŠØ©",
    "MatÃ©riels et Ã©quipements":         "Ù…Ø¹Ø¯Ø§Øª ÙˆØªØ¬Ù‡ÙŠØ²Ø§Øª",
    "VÃ©hicules et matÃ©riels roulants":  "Ù…Ø±ÙƒØ¨Ø§Øª ÙˆÙ…Ø¹Ø¯Ø§Øª Ù…ØªÙ†Ù‚Ù„Ø©",
    "Services informatiques":           "Ø®Ø¯Ù…Ø§Øª Ù…Ø¹Ù„ÙˆÙ…Ø§ØªÙŠØ©",
    "Services de gardiennage":          "Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø­Ø±Ø§Ø³Ø©",
    "Services de nettoyage":            "Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ù†Ø¸Ø§ÙØ©",
    "Services de transport":            "Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ù†Ù‚Ù„",
    "Services de restauration":         "Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø¥Ø·Ø¹Ø§Ù…",
    "Prestations d'Ã©tudes":             "Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø¯Ø±Ø§Ø³Ø§Øª",
    "Prestations d'audit":              "Ø®Ø¯Ù…Ø§Øª Ø§Ù„ØªØ¯Ù‚ÙŠÙ‚",
    "Prestations de formation":         "Ø®Ø¯Ù…Ø§Øª Ø§Ù„ØªÙƒÙˆÙŠÙ†",
    "Prestations d'assurance":          "Ø®Ø¯Ù…Ø§Øª Ø§Ù„ØªØ£Ù…ÙŠÙ†",
    "Prestations mÃ©dicales":            "Ø§Ù„Ø®Ø¯Ù…Ø§Øª Ø§Ù„Ø·Ø¨ÙŠØ©",
    "Services divers":                  "Ø®Ø¯Ù…Ø§Øª Ù…ØªÙ†ÙˆØ¹Ø©",
}

def extract_official_domain(soup, full_text):
    """ÙŠØ³ØªØ®Ø±Ø¬ Ø§Ù„ØªØµÙ†ÙŠÙ Ù…Ø¨Ø§Ø´Ø±Ø© Ù…Ù† HTML Ø§Ù„Ù…ÙˆÙ‚Ø¹ Ø§Ù„Ø±Ø³Ù…ÙŠ"""
    # Ù…Ø­Ø§ÙˆÙ„Ø© 1: Ø§Ù„Ø¨Ø­Ø« Ø¹Ù† Ø­Ù‚Ù„ "Nature" Ø£Ùˆ "Type" Ø£Ùˆ "CatÃ©gorie" ÙÙŠ Ø§Ù„Ø¬Ø¯ÙˆÙ„
    for label in ['Nature', 'Type de prestation', 'CatÃ©gorie', 'Secteur', 
                  'Type', 'Nature des prestations', 'Domaine']:
        el = soup.find(string=re.compile(rf'^\s*{label}\s*$', re.I))
        if el:
            p = el.parent
            if p:
                nxt = p.find_next_sibling()
                if nxt:
                    val = nxt.get_text(strip=True)
                    if val and len(val) > 2:
                        return val[:80]
                # Ø£Ùˆ ÙÙŠ Ù†ÙØ³ Ø§Ù„Ø®Ù„ÙŠØ© Ø¨Ø¹Ø¯ ":"
                txt = p.get_text(strip=True)
                if ':' in txt:
                    val = txt.split(':',1)[-1].strip()
                    if val: return val[:80]
    
    # Ù…Ø­Ø§ÙˆÙ„Ø© 2: Ø§Ù„Ø¨Ø­Ø« ÙÙŠ Ø§Ù„Ù€ labels/th/dt
    for tag in soup.find_all(['th','dt','td','label','strong','b']):
        txt = tag.get_text(strip=True)
        if re.search(r'^(Nature|Type|CatÃ©gorie|Secteur)\s*:?$', txt, re.I):
            nxt = tag.find_next_sibling() or (tag.parent.find_next_sibling() if tag.parent else None)
            if nxt:
                val = nxt.get_text(strip=True)
                if val and 3 < len(val) < 100:
                    return val
    
    # Ù…Ø­Ø§ÙˆÙ„Ø© 3: patterns ÙÙŠ Ø§Ù„Ù†Øµ Ø§Ù„ÙƒØ§Ù…Ù„
    patterns = [
        r'Nature\s*(?:des prestations)?\s*:?\s*([A-ZÃ€-Ãœ][^\n\r|]{3,60})',
        r'Type\s*(?:de prestation)?\s*:?\s*([A-ZÃ€-Ãœ][^\n\r|]{3,60})',
        r'CatÃ©gorie\s*:?\s*([A-ZÃ€-Ãœ][^\n\r|]{3,60})',
        r'Secteur\s*:?\s*([A-ZÃ€-Ãœ][^\n\r|]{3,60})',
    ]
    for p in patterns:
        m = re.search(p, full_text, re.I)
        if m:
            val = m.group(1).strip()[:80]
            # ØªØ­Ù‚Ù‚ Ø£Ù†Ù‡Ø§ Ù„ÙŠØ³Øª Ù‚ÙŠÙ…Ø© Ø¹Ø´ÙˆØ§Ø¦ÙŠØ©
            if len(val) > 3 and not any(x in val.lower() for x in ['http','www','@']):
                return val
    
    return None

def classify_domain(text):
    """ØªØµÙ†ÙŠÙ Ø§Ø­ØªÙŠØ§Ø·ÙŠ Ø¨Ø§Ù„ÙƒÙ„Ù…Ø§Øª Ø§Ù„Ù…ÙØªØ§Ø­ÙŠØ© Ø¥Ø°Ø§ Ù„Ù… ÙŠÙˆØ¬Ø¯ ØªØµÙ†ÙŠÙ Ø±Ø³Ù…ÙŠ"""
    t = text.lower()
    for d, kws in DOMAINS_FR.items():
        if any(k in t for k in kws): return d
    return "Autres services"

def normalize_domain(raw):
    """ØªØ·Ø¨ÙŠØ¹ Ø§Ù„ØªØµÙ†ÙŠÙ Ø§Ù„Ù…Ø³ØªØ®Ø±Ø¬ Ù„Ù„ØªØ£ÙƒØ¯ Ù…Ù† ØªÙˆØ­ÙŠØ¯Ù‡"""
    if not raw: return None
    raw = raw.strip()
    # Ù…Ø·Ø§Ø¨Ù‚Ø© Ù…Ø¨Ø§Ø´Ø±Ø© Ù…Ø¹ Ø§Ù„ØªØµÙ†ÙŠÙØ§Øª Ø§Ù„Ø±Ø³Ù…ÙŠØ©
    for official in OFFICIAL_DOMAINS:
        if official.lower() in raw.lower() or raw.lower() in official.lower():
            return official
    # Ø¥Ø±Ø¬Ø§Ø¹ Ø§Ù„Ù‚ÙŠÙ…Ø© ÙƒÙ…Ø§ Ù‡ÙŠ Ø¥Ø°Ø§ ÙƒØ§Ù†Øª Ù…Ø¹Ù‚ÙˆÙ„Ø©
    if 3 < len(raw) < 80:
        return raw
    return None

def classify_region(text):
    u = text.upper()
    for region, data in REGIONS.items():
        if any(v in u for v in data["villes"]): return region
    return ""

def is_cancelled(text):
    t = text.lower()
    return any(k in t for k in CANCEL_KEYWORDS)

def generate_summary(text, objet, domaine, lang='fr'):
    qty_m = re.search(r'(\d+[\s]*(?:unitÃ©s?|lots?|piÃ¨ces?|kits?))', text, re.I)
    qty = qty_m.group(1) if qty_m else ""
    dur_m = re.search(r'(\d+[\s]*(?:mois|ans?|jours?))', text, re.I)
    dur = dur_m.group(1) if dur_m else ""
    if lang == 'ar':
        domain_ar = DOMAINS_AR.get(domaine, domaine)
        s = f"ØªØ·Ù„Ø¨ Ù‡Ø°Ù‡ Ø§Ù„ØµÙÙ‚Ø© {domain_ar}"
        if qty: s += f" Ø¨ÙƒÙ…ÙŠØ© {qty}"
        if dur:  s += f" Ù„Ù…Ø¯Ø© {dur}"
        s += ". ÙŠÙÙ†ØµØ­ Ø¨Ø§Ù„ØªØ­Ù‚Ù‚ Ù…Ù† Ø§Ù„Ù…ØªØ·Ù„Ø¨Ø§Øª Ø§Ù„ÙÙ†ÙŠØ© ÙÙŠ ÙˆØ«ÙŠÙ‚Ø© Ø§Ù„Ø¯Ø¹ÙˆØ©."
    else:
        s = f"Ce marchÃ© porte sur {domaine.lower()}"
        if qty: s += f" ({qty})"
        if dur:  s += f" pour {dur}"
        s += ". VÃ©rifiez les spÃ©cifications dans le dossier d'appel d'offres."
    return s

def extract_clauses(text):
    clauses = []
    patterns = [
        r'(?:capacitÃ©|expÃ©rience|rÃ©fÃ©rence|attestation|certificat|agrÃ©ment|qualification)[^.]{5,80}',
        r'(?:dossier|document|piÃ¨ce justificative)[^.]{5,60}',
        r'(?:caution|garantie)[^.]{5,60}',
        r'(?:dÃ©lai|durÃ©e)[^.]{5,60}',
        r'(?:critÃ¨re|Ã©valuation)[^.]{5,60}',
    ]
    for p in patterns:
        for m in re.findall(p, text, re.I)[:2]:
            m = m.strip()[:100]
            if len(m) > 20 and m not in clauses:
                clauses.append(m)
    return clauses[:6]

def extract_date(text):
    for p in [r'\d{2}/\d{2}/\d{4}', r'\d{4}-\d{2}-\d{2}']:
        m = re.search(p, str(text))
        if m: return m.group(0)
    return ""

def get_suppliers(domaine):
    return SUPPLIERS.get(domaine, [])

# â”€â”€ DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tenders (
        id TEXT PRIMARY KEY, objet TEXT, acheteur TEXT,
        region TEXT, ville TEXT, domaine TEXT, montant TEXT,
        date_publication TEXT, date_limite TEXT, description TEXT,
        clauses TEXT, summary TEXT, statut TEXT DEFAULT 'actif',
        url TEXT, date_extraction TEXT
    );
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL, entreprise TEXT,
        phone TEXT UNIQUE NOT NULL, email TEXT,
        whatsapp TEXT, telegram TEXT,
        domaines TEXT DEFAULT '[]', regions TEXT DEFAULT '[]',
        langue TEXT DEFAULT 'fr', plan TEXT DEFAULT 'free',
        actif INTEGER DEFAULT 1, token TEXT UNIQUE,
        created_at TEXT, notif_count INTEGER DEFAULT 0, last_login TEXT
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER, tender_id TEXT,
        channel TEXT, sent_at TEXT, status TEXT DEFAULT 'sent'
    );
    CREATE TABLE IF NOT EXISTS payment_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT, email TEXT, method TEXT,
        amount INTEGER DEFAULT 99, status TEXT DEFAULT 'pending', created_at TEXT
    );
    """)
    try: db.execute("ALTER TABLE tenders ADD COLUMN summary TEXT")
    except: pass
    try: db.execute("ALTER TABLE tenders ADD COLUMN statut TEXT DEFAULT 'actif'")
    except: pass
    db.commit()
    return db

# Global DB for reads, thread-safe
import threading
_local = threading.local()

def get_db():
    if not hasattr(_local, 'conn'):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn

DB = init_db()

def fresh_db():
    """Always returns a fresh thread-safe SQLite connection"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_exec(sql, params=()):
    """Thread-safe DB execute"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        conn.commit()
        result = cur.fetchall()
        conn.close()
        return result
    except Exception as e:
        print(f"DB error: {e}")
        return []

def db_one(sql, params=()):
    """Thread-safe DB fetchone"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        result = cur.fetchone()
        conn.close()
        return result
    except Exception as e:
        print(f"DB error: {e}")
        return None

def db_val(sql, params=()):
    """Thread-safe DB single value"""
    try:
        row = db_one(sql, params)
        return row[0] if row else 0
    except Exception as e:
        print(f"DB error: {e}")
        return 0

def make_token(phone):
    return hashlib.md5(f"{phone}rassd2026".encode()).hexdigest()[:16]

# â”€â”€ Scraper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def parse_tender(html, tid):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    full = soup.get_text(' ', strip=True)
    statut = 'annule' if is_cancelled(full) else 'actif'
    def fv(labels):
        for l in labels:
            el = soup.find(string=re.compile(l, re.I))
            if el:
                p = el.parent
                if p:
                    n = p.find_next_sibling()
                    if n: return n.get_text(strip=True)[:200]
                    t = p.get_text(strip=True)
                    if ':' in t: return t.split(':',1)[-1].strip()[:200]
        return ''
    objet    = fv(['Objet','intitulÃ©','DÃ©signation']) or f"Consultation #{tid}"
    acheteur = fv(['Acheteur','organisme','Pouvoir adjudicateur'])
    lim_m    = re.search(r'[Dd]ate\s+limite[^:]*?(\d{2}[/\-]\d{2}[/\-]\d{4})', full)
    date_lim = lim_m.group(1) if lim_m else extract_date(full[200:600])
    # Ø§Ø³ØªØ®Ø±Ø§Ø¬ Ø§Ù„ØªØµÙ†ÙŠÙ Ø§Ù„Ø±Ø³Ù…ÙŠ Ù…Ù† Ø§Ù„Ù…ÙˆÙ‚Ø¹ Ø£ÙˆÙ„Ø§Ù‹
    raw_domain = extract_official_domain(soup, full)
    domaine = normalize_domain(raw_domain) or classify_domain(f"{objet} {full[:400]}")
    region   = classify_region(f"{acheteur} {full[:500]}")
    ville    = ""
    for r, data in REGIONS.items():
        u = full.upper()
        for v in data["villes"]:
            if v in u:
                ville = v.title()
                if not region: region = r
                break
        if ville: break
    desc_parts = [s.strip() for s in full.split('  ') if len(s.strip()) > 30]
    description = ' | '.join(desc_parts[:4])[:500]
    return {
        'id': str(tid), 'objet': objet, 'acheteur': acheteur,
        'region': region, 'ville': ville, 'domaine': domaine,
        'montant': fv(['Montant','Budget','Estimation']),
        'date_publication': extract_date(full[:400]),
        'date_limite': date_lim, 'description': description,
        'clauses': json.dumps(extract_clauses(full), ensure_ascii=False),
        'summary': generate_summary(full, objet, domaine, 'fr'),
        'statut': statut, 'url': f"{SHOW_URL}{tid}",
        'date_extraction': datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

def save_tender(t):
    try:
        DB.execute("""INSERT OR IGNORE INTO tenders
            (id,objet,acheteur,region,ville,domaine,montant,date_publication,
             date_limite,description,clauses,summary,statut,url,date_extraction)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t['id'],t['objet'],t['acheteur'],t['region'],t['ville'],t['domaine'],
             t['montant'],t['date_publication'],t['date_limite'],t['description'],
             t['clauses'],t.get('summary',''),t.get('statut','actif'),t['url'],t['date_extraction']))
        DB.commit()
        return DB.execute("SELECT changes()").fetchone()[0] > 0
    except Exception as e:
        print(f"DB error: {e}")
        return False

def scrape_sync():
    import requests
    from bs4 import BeautifulSoup
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": random.choice(UAS), "Accept-Language": "fr-FR,fr;q=0.9"})
    try: s.get(BASE_URL, timeout=10)
    except: pass
    new_tenders = []
    known = set(r[0] for r in DB.execute("SELECT id FROM tenders"))
    max_id = DB.execute("SELECT MAX(CAST(id AS INTEGER)) FROM tenders").fetchone()[0] or 300000
    for page in range(1, 5):
        url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
        try:
            r = s.get(url, timeout=20)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            ids = []
            for a in soup.find_all('a', href=re.compile(r'/consultation/show/(\d+)')):
                m = re.search(r'/show/(\d+)', a['href'])
                if m: ids.append(m.group(1))
            for tid in set(ids):
                if tid not in known:
                    try:
                        resp = s.get(f"{SHOW_URL}{tid}", timeout=15)
                        if resp.status_code == 200:
                            t = parse_tender(resp.text, tid)
                            if save_tender(t):
                                known.add(tid)
                                if t.get('statut') == 'actif':
                                    new_tenders.append(t)
                        time.sleep(random.uniform(0.5, 1.5))
                    except: pass
        except: pass
        time.sleep(random.uniform(2, 4))
    fail, cur = 0, max_id + 1
    while fail < 8 and len(new_tenders) < 25:
        try:
            r = s.get(f"{SHOW_URL}{cur}", timeout=10)
            if r.status_code == 404: fail += 1
            elif r.status_code == 200:
                fail = 0
                if str(cur) not in known:
                    t = parse_tender(r.text, str(cur))
                    if save_tender(t):
                        known.add(str(cur))
                        if t.get('statut') == 'actif':
                            new_tenders.append(t)
        except: fail += 1
        cur += 1
        time.sleep(random.uniform(0.3, 1.0))
    return new_tenders

# â”€â”€ Notifications â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def send_email(to_email, subject, html):
    if not to_email or not GMAIL_USER: return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Ø´Ø¨ÙƒØ© Ø±ØµØ¯ <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS.replace(" ", ""))
            s.send_message(msg)
    except Exception as e:
        print(f"Email error: {e}")

async def send_telegram(chat_id, msg):
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        except: pass

def build_suppliers_html(domaine, lang='fr'):
    suppliers = get_suppliers(domaine)
    if not suppliers: return ""
    title = "ðŸª Ù…ÙˆØ±Ø¯ÙˆÙ† Ù…Ù‚ØªØ±Ø­ÙˆÙ†" if lang=='ar' else "ðŸª Fournisseurs recommandÃ©s"
    rows = ""
    for sup in suppliers[:3]:
        rows += f"""<tr>
          <td style="padding:10px;border-bottom:1px solid #f5efe6"><strong style="color:#8B4513">{sup['nom']}</strong><br>
          <span style="font-size:11px;color:#888">ðŸ“ {sup['ville']}</span></td>
          <td style="padding:10px;border-bottom:1px solid #f5efe6;font-size:12px">{sup['desc']}</td>
          <td style="padding:10px;border-bottom:1px solid #f5efe6;font-size:11px">ðŸ“ž {sup['tel']}<br>ðŸŒ {sup['site']}</td>
        </tr>"""
    return f"""<div style="margin-top:20px;background:#fdf6ee;border-radius:10px;padding:16px;border:1px solid #e8d5b7">
      <h3 style="margin:0 0 12px;font-size:14px;color:#8B4513">{title}</h3>
      <table style="width:100%;border-collapse:collapse;font-size:12px"><tr style="background:#f5efe6">
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">Ø§Ù„Ù…ÙˆØ±Ø¯</th>
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">Ø§Ù„ÙˆØµÙ</th>
        <th style="padding:8px;text-align:right;font-size:11px;color:#5D2E0C">Ø§Ù„ØªÙˆØ§ØµÙ„</th>
      </tr>{rows}</table></div>"""

def build_email_html(contractor, tender, lang):
    clauses = []
    try: clauses = json.loads(tender['clauses'] or '[]')
    except: pass
    region_ar = REGIONS.get(tender['region'], {}).get('ar', tender['region'])
    domain_ar = DOMAINS_AR.get(tender['domaine'], tender['domaine'])
    token     = contractor['token']
    summary   = tender.get('summary') or ''
    grad      = "linear-gradient(135deg,#1a0a00,#8B4513)"

    clauses_html = ""
    if clauses:
        items = "".join(f"<li style='padding:4px 0;font-size:12px'>{c}</li>" for c in clauses)
        title = "ðŸ“‹ Ø§Ù„Ø¨Ù†ÙˆØ¯ ÙˆØ§Ù„Ù…ØªØ·Ù„Ø¨Ø§Øª" if lang=='ar' else "ðŸ“‹ Clauses"
        clauses_html = f"""<div style='margin-top:16px;background:#fdf6ee;padding:14px;border-radius:8px;border:1px solid #e8d5b7'>
            <strong style='font-size:13px;color:#8B4513'>{title}:</strong>
            <ul style='margin:8px 0 0 20px;color:#374151'>{items}</ul></div>"""

    summary_html = ""
    if summary:
        title = "ðŸ’¡ Ù…Ù„Ø®Øµ" if lang=='ar' else "ðŸ’¡ RÃ©sumÃ©"
        summary_html = f"""<div style='margin-top:16px;background:#f0ece8;padding:14px;border-radius:8px;border:1px solid #d4c5b0'>
            <strong style='font-size:13px;color:#5D2E0C'>{title}:</strong>
            <p style='margin:6px 0 0;font-size:12px;color:#374151'>{summary}</p></div>"""

    suppliers_html = build_suppliers_html(tender['domaine'], lang) if tender['domaine'] in GOODS_DOMAINS else ""

    if lang == 'ar':
        return f"""<div dir="rtl" style="font-family:Cairo,Arial,sans-serif;max-width:620px;margin:0 auto;background:#f9f5f0;padding:20px">
          <div style="background:{grad};color:white;padding:24px;border-radius:14px 14px 0 0;text-align:center">
            <h1 style="margin:0;font-size:22px">ðŸ“¡ Ø´Ø¨ÙƒØ© Ø±ØµØ¯</h1>
            <p style="margin:6px 0 0;opacity:.85;font-size:13px">ØµÙÙ‚Ø© Ø¬Ø¯ÙŠØ¯Ø© Ù…Ù†Ø§Ø³Ø¨Ø© Ù„Ù…Ù„ÙÙƒ</p>
          </div>
          <div style="background:white;padding:24px;border-radius:0 0 14px 14px;border:1px solid #e8d5b7">
            <h2 style="font-size:15px;color:#1a0a00;margin-bottom:16px">{tender['objet']}</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6;width:35%">Ø§Ù„Ø¬Ù‡Ø© Ø§Ù„Ù…Ø´ØªØ±ÙŠØ©</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['acheteur'] or 'â€”'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Ø§Ù„Ø¬Ù‡Ø©</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{region_ar or 'â€”'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Ø§Ù„Ù…Ø¬Ø§Ù„</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{domain_ar}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Ø§Ù„Ù…ÙŠØ²Ø§Ù†ÙŠØ©</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['montant'] or 'ØºÙŠØ± Ù…Ø­Ø¯Ø¯'}</td></tr>
              <tr><td style="padding:9px;color:#dc2626">Ø¢Ø®Ø± Ø£Ø¬Ù„</td><td style="padding:9px;font-weight:900;color:#dc2626">{tender['date_limite'] or 'â€”'}</td></tr>
            </table>
            {summary_html}{clauses_html}{suppliers_html}
            <a href="{tender['url']}" style="display:block;background:{grad};color:white;text-align:center;padding:13px;border-radius:9px;text-decoration:none;font-weight:700;margin-top:20px">ðŸ”— ÙØªØ­ Ø§Ù„ØµÙÙ‚Ø© ÙÙŠ Ø§Ù„Ø¨ÙˆØ§Ø¨Ø© Ø§Ù„Ø±Ø³Ù…ÙŠØ©</a>
            <a href="/dashboard/{token}" style="display:block;background:#f5efe6;color:#1a0a00;text-align:center;padding:10px;border-radius:9px;text-decoration:none;font-size:13px;margin-top:8px">ðŸ“Š Ù…Ù„ÙÙƒ Ø§Ù„Ø´Ø®ØµÙŠ</a>
          </div>
          <p style="text-align:center;font-size:11px;color:#aaa;margin-top:12px">Ø´Ø¨ÙƒØ© Ø±ØµØ¯ â€” Ù…Ø±Ø§Ù‚Ø¨Ø© Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ø¹Ù…ÙˆÙ…ÙŠØ© Ø§Ù„Ù…ØºØ±Ø¨ÙŠØ©</p>
        </div>"""
    else:
        return f"""<div style="font-family:Inter,Arial,sans-serif;max-width:620px;margin:0 auto;background:#f9f5f0;padding:20px">
          <div style="background:{grad};color:white;padding:24px;border-radius:14px 14px 0 0;text-align:center">
            <h1 style="margin:0;font-size:22px">ðŸ“¡ Shabaka Rassd</h1>
            <p style="margin:6px 0 0;opacity:.85;font-size:13px">Nouveau marchÃ© correspondant Ã  votre profil</p>
          </div>
          <div style="background:white;padding:24px;border-radius:0 0 14px 14px;border:1px solid #e8d5b7">
            <h2 style="font-size:15px;color:#1a0a00;margin-bottom:16px">{tender['objet']}</h2>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6;width:35%">Acheteur</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['acheteur'] or 'â€”'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">RÃ©gion</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['region'] or 'â€”'}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Secteur</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['domaine']}</td></tr>
              <tr><td style="padding:9px;color:#888;border-bottom:1px solid #f5efe6">Budget</td><td style="padding:9px;font-weight:700;border-bottom:1px solid #f5efe6">{tender['montant'] or 'Non prÃ©cisÃ©'}</td></tr>
              <tr><td style="padding:9px;color:#dc2626">Date limite</td><td style="padding:9px;font-weight:900;color:#dc2626">{tender['date_limite'] or 'â€”'}</td></tr>
            </table>
            {summary_html}{clauses_html}{suppliers_html}
            <a href="{tender['url']}" style="display:block;background:{grad};color:white;text-align:center;padding:13px;border-radius:9px;text-decoration:none;font-weight:700;margin-top:20px">ðŸ”— Voir le marchÃ© sur le portail officiel</a>
            <a href="/dashboard/{token}" style="display:block;background:#f5efe6;color:#1a0a00;text-align:center;padding:10px;border-radius:9px;text-decoration:none;font-size:13px;margin-top:8px">ðŸ“Š Mon tableau de bord</a>
          </div>
          <p style="text-align:center;font-size:11px;color:#aaa;margin-top:12px">Shabaka Rassd â€” Veille des marchÃ©s publics marocains</p>
        </div>"""

def match(contractor, tender):
    if tender.get('statut') == 'annule': return False
    c_domains = json.loads(contractor['domaines'] or '[]')
    c_regions  = json.loads(contractor['regions']  or '[]')
    if c_regions and tender['region'] and tender['region'] not in c_regions: return False
    if c_domains and tender['domaine'] not in c_domains and tender['domaine'] != 'Autres services': return False
    return True

async def notify_all(new_tenders):
    if not new_tenders: return
    conn = fresh_db()
    contractors = conn.execute("SELECT * FROM contractors WHERE plan='premium' AND actif=1 AND email IS NOT NULL AND email!=''").fetchall()
    conn.close()
    for c in contractors:
        c = dict(c)
        lang = c.get('langue', 'fr')
        for t in new_tenders:
            t = dict(t) if not isinstance(t, dict) else t
            if not match(c, t): continue
            html    = build_email_html(c, t, lang)
            subject = f"ðŸ“¡ {'ØµÙÙ‚Ø© Ø¬Ø¯ÙŠØ¯Ø©' if lang=='ar' else 'Nouveau marchÃ©'}: {t['objet'][:50]}"
            await send_email(c['email'], subject, html)
            if c.get('telegram'):
                await send_telegram(c['telegram'],
                    f"ðŸ”” *Ø´Ø¨ÙƒØ© Ø±ØµØ¯*\n\nðŸ“‹ *{t['objet'][:80]}*\nðŸ“… {t['date_limite'] or 'â€”'}\nðŸ”— {t['url']}")
            try:
                wconn = fresh_db()
                wconn.execute("INSERT INTO notifications (contractor_id,tender_id,channel,sent_at) VALUES(?,?,?,?)",
                           (c['id'], t['id'], 'email', datetime.now().strftime("%Y-%m-%d %H:%M")))
                wconn.execute("UPDATE contractors SET notif_count=notif_count+1 WHERE id=?", (c['id'],))
                wconn.commit()
                wconn.close()
            except Exception as e:
                print(f"Notify DB error: {e}")

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(daily_scrape())
    yield

async def daily_scrape():
    while True:
        await asyncio.sleep(86400)
        print("[Scheduler] Running daily scrape...")
        new = await asyncio.get_event_loop().run_in_executor(None, scrape_sync)
        await notify_all(new)

app = FastAPI(lifespan=lifespan)
for d in ["static","static/css","static/js"]:
    Path(d).mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    stats = {
        "tenders":     fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "contractors": fresh_db().execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "cancelled":   fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "regions":     len(REGIONS),
    }
    recent      = fresh_db().execute("SELECT * FROM tenders WHERE statut='actif' OR statut IS NULL ORDER BY date_extraction DESC LIMIT 6").fetchall()
    top_regions = fresh_db().execute("SELECT region, COUNT(*) as cnt FROM tenders WHERE region!='' GROUP BY region ORDER BY cnt DESC LIMIT 12").fetchall()
    return templates.TemplateResponse("landing.html", {
        "request": request, "stats": stats,
        "recent": recent, "top_regions": top_regions,
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR,
    })

@app.get("/tenders", response_class=HTMLResponse)
async def tenders_list(request: Request, region: str="", domaine: str="",
    q: str="", statut: str="actif", page: int=1):
    per_page = 20
    offset   = (page-1)*per_page
    conds, params = ["1=1"], []
    if statut == "actif":  conds.append("(statut='actif' OR statut IS NULL)")
    elif statut == "annule": conds.append("statut='annule'")
    if region:  conds.append("region=?");  params.append(region)
    if domaine: conds.append("domaine=?"); params.append(domaine)
    if q:       conds.append("(objet LIKE ? OR acheteur LIKE ?)"); params += [f"%{q}%",f"%{q}%"]
    where = " AND ".join(conds)
    total = fresh_db().execute(f"SELECT COUNT(*) FROM tenders WHERE {where}", params).fetchone()[0]
    rows  = fresh_db().execute(f"SELECT * FROM tenders WHERE {where} ORDER BY date_extraction DESC LIMIT ? OFFSET ?",
                       params+[per_page,offset]).fetchall()
    pages = (total+per_page-1)//per_page
    return templates.TemplateResponse("tenders_public.html", {
        "request": request, "tenders": rows,
        "region": region, "domaine": domaine, "q": q, "statut": statut,
        "page": page, "pages": pages, "total": total,
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/tender/{tid}", response_class=HTMLResponse)
async def tender_detail(request: Request, tid: str):
    t = fresh_db().execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
    if not t: raise HTTPException(404)
    t = dict(t)
    clauses   = []
    try: clauses = json.loads(t['clauses'] or '[]')
    except: pass
    suppliers = get_suppliers(t['domaine']) if t['domaine'] in GOODS_DOMAINS else []
    return templates.TemplateResponse("tender_public.html", {
        "request": request, "tender": t, "clauses": clauses,
        "suppliers": suppliers, "REGIONS": REGIONS, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {
        "request": request, "REGIONS": REGIONS,
        "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.post("/register")
async def register_submit(request: Request,
    nom: str=Form(...), entreprise: str=Form(""),
    phone: str=Form(...), email: str=Form(""),
    whatsapp: str=Form(""), telegram: str=Form(""), langue: str=Form("fr")):
    form     = await request.form()
    domaines = json.dumps(form.getlist("domaines"))
    regions  = json.dumps(form.getlist("regions"))
    token    = make_token(re.sub(r'\s+','',phone))
    try:
        wdb = fresh_db()
        wdb.execute("""INSERT INTO contractors
            (nom,entreprise,phone,email,whatsapp,telegram,domaines,regions,langue,token,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (nom,entreprise,re.sub(r'\s+','',phone),email,whatsapp,telegram,
             domaines,regions,langue,token,datetime.now().strftime("%Y-%m-%d %H:%M")))
        wdb.commit()
        wdb.close()
    except Exception as e:
        print(f"Register error: {e}")
    return RedirectResponse(f"/dashboard/{token}", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_submit(request: Request, phone: str=Form(...)):
    try:
        token = make_token(re.sub(r'\s+','',phone))
        c = fresh_db().execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
        if not c:
            return templates.TemplateResponse("login.html", {
                "request": request, "error": "Ø±Ù‚Ù… Ø§Ù„Ù‡Ø§ØªÙ ØºÙŠØ± Ù…ÙˆØ¬ÙˆØ¯. Ø³Ø¬Ù‘Ù„ Ø£ÙˆÙ„Ø§Ù‹."})
        try:
            wdb = fresh_db()
            wdb.execute("UPDATE contractors SET last_login=? WHERE token=?",
                       (datetime.now().strftime("%Y-%m-%d %H:%M"), token))
            wdb.commit()
            wdb.close()
        except: pass
        return RedirectResponse(f"/dashboard/{token}", status_code=302)
    except Exception as e:
        print(f"Login error: {e}")
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Ø®Ø·Ø£ ØªÙ‚Ù†ÙŠ. Ø­Ø§ÙˆÙ„ Ù…Ø¬Ø¯Ø¯Ø§Ù‹."})

@app.get("/dashboard/{token}", response_class=HTMLResponse)
async def dashboard(request: Request, token: str):
    c = fresh_db().execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
    if not c: raise HTTPException(404)
    c    = dict(c)
    lang = c.get('langue','fr')
    stats = {
        "total":   fresh_db().execute("SELECT COUNT(*) FROM notifications WHERE contractor_id=?", (c['id'],)).fetchone()[0],
        "month":   fresh_db().execute("SELECT COUNT(*) FROM notifications WHERE contractor_id=? AND sent_at LIKE ?",
                              (c['id'], datetime.now().strftime("%Y-%m")+"%")).fetchone()[0],
        "tenders": fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
    }
    recent = fresh_db().execute("""SELECT t.* FROM tenders t
        JOIN notifications n ON t.id=n.tender_id
        WHERE n.contractor_id=? ORDER BY n.sent_at DESC LIMIT 5""", (c['id'],)).fetchall()
    all_active = fresh_db().execute("SELECT * FROM tenders WHERE statut='actif' OR statut IS NULL ORDER BY date_extraction DESC LIMIT 20").fetchall()
    matching   = [t for t in all_active if match(c, dict(t))][:5]
    return templates.TemplateResponse("dashboard_contractor.html", {
        "request": request, "lang": lang, "contractor": c, "token": token,
        "stats": stats, "recent": recent, "matching": matching,
        "REGIONS": REGIONS, "DOMAINS_AR": DOMAINS_AR,
    })

@app.get("/profile/{token}", response_class=HTMLResponse)
async def profile_edit_page(request: Request, token: str):
    c = fresh_db().execute("SELECT * FROM contractors WHERE token=?", (token,)).fetchone()
    if not c: raise HTTPException(404)
    c = dict(c)
    return templates.TemplateResponse("profile_edit.html", {
        "request": request, "lang": c.get('langue','fr'), "contractor": c, "token": token,
        "c_domaines": json.loads(c['domaines'] or '[]'),
        "c_regions":  json.loads(c['regions']  or '[]'),
        "REGIONS": REGIONS, "DOMAINS_FR": DOMAINS_FR, "DOMAINS_AR": DOMAINS_AR,
    })

@app.post("/profile/{token}")
async def profile_edit_submit(request: Request, token: str,
    nom: str=Form(...), entreprise: str=Form(""),
    email: str=Form(""), whatsapp: str=Form(""),
    telegram: str=Form(""), langue: str=Form("fr")):
    form     = await request.form()
    domaines = json.dumps(form.getlist("domaines"))
    regions  = json.dumps(form.getlist("regions"))
    wdb = fresh_db()
    wdb.execute("""UPDATE contractors SET
        nom=?,entreprise=?,email=?,whatsapp=?,telegram=?,
        domaines=?,regions=?,langue=? WHERE token=?""",
        (nom,entreprise,email,whatsapp,telegram,domaines,regions,langue,token))
    wdb.commit()
    wdb.close()
    return RedirectResponse(f"/dashboard/{token}", status_code=302)

@app.get("/upgrade", response_class=HTMLResponse)
async def upgrade_page(request: Request):
    return templates.TemplateResponse("upgrade.html", {"request": request})

@app.post("/upgrade")
async def upgrade_submit(request: Request,
    phone: str=Form(...), email: str=Form(""), method: str=Form("virement")):
    wdb = fresh_db()
    wdb.execute("INSERT OR IGNORE INTO payment_requests (phone,email,method,created_at) VALUES(?,?,?,?)",
               (re.sub(r'\s+','',phone), email, method, datetime.now().strftime("%Y-%m-%d %H:%M")))
    wdb.commit()
    wdb.close()
    return templates.TemplateResponse("merci.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, pwd: str=""):
    if pwd != ADMIN_PASS:
        return templates.TemplateResponse("admin_login.html", {"request": request})
    stats = {
        "tenders":     fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "cancelled":   fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "contractors": fresh_db().execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "premium":     fresh_db().execute("SELECT COUNT(*) FROM contractors WHERE plan='premium'").fetchone()[0],
        "notifs":      fresh_db().execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
        "pending":     fresh_db().execute("SELECT COUNT(*) FROM payment_requests WHERE status='pending'").fetchone()[0],
        "payments":    fresh_db().execute("SELECT COUNT(*) FROM payment_requests WHERE status='pending'").fetchone()[0],
    }
    contractors = fresh_db().execute("SELECT * FROM contractors ORDER BY created_at DESC").fetchall()
    payments    = fresh_db().execute("SELECT * FROM payment_requests WHERE status='pending' ORDER BY created_at DESC").fetchall()
    top_regions = fresh_db().execute("SELECT region, COUNT(*) as cnt FROM tenders WHERE region!='' GROUP BY region ORDER BY cnt DESC").fetchall()
    return templates.TemplateResponse("admin.html", {
        "request": request, "pwd": pwd, "stats": stats,
        "contractors": contractors, "payments": payments,
        "top_regions": top_regions, "REGIONS": REGIONS,
    })

@app.get("/admin/activate")
async def admin_activate(phone: str, pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    phone_clean = re.sub(r'\s+','',phone)
    wdb = fresh_db()
    wdb.execute("UPDATE contractors SET plan='premium' WHERE phone=?", (phone_clean,))
    wdb.execute("UPDATE payment_requests SET status='paid' WHERE phone=?", (phone_clean,))
    wdb.commit()
    wdb.close()
    c = fresh_db().execute("SELECT * FROM contractors WHERE phone=?", (phone_clean,)).fetchone()
    if c:
        c = dict(c)
        await send_email(c.get('email'), "âœ… ØªÙ… ØªÙØ¹ÙŠÙ„ Ø§Ø´ØªØ±Ø§ÙƒÙƒ Premium â€” Ø´Ø¨ÙƒØ© Ø±ØµØ¯",
            f"""<div style="text-align:center;padding:30px;font-family:Cairo,Arial">
            <h2 style="color:#8B4513">âœ… ØªÙ… ØªÙØ¹ÙŠÙ„ Ø­Ø³Ø§Ø¨Ùƒ Premium!</h2>
            <p>Ù…Ø±Ø­Ø¨Ø§Ù‹ {c['nom']}ØŒ Ø­Ø³Ø§Ø¨Ùƒ Ù…ÙØ¹Ù‘Ù„ Ø§Ù„Ø¢Ù†.</p>
            <a href="/dashboard/{c['token']}" style="background:#8B4513;color:white;padding:12px 24px;border-radius:8px;text-decoration:none">Ø¹Ø±Ø¶ Ù…Ù„ÙÙƒ Ø§Ù„Ø´Ø®ØµÙŠ</a></div>""")
    return JSONResponse({"status": "ok"})

@app.get("/admin/scrape")
async def admin_scrape(pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    async def run():
        new = await asyncio.get_event_loop().run_in_executor(None, scrape_sync)
        await notify_all(new)
        print(f"[Scrape] {len(new)} new tenders")
    asyncio.create_task(run())
    return JSONResponse({"status": "Scraping lancÃ©..."})

@app.get("/admin/reclassify")
async def admin_reclassify(pwd: str=""):
    """Ø¥Ø¹Ø§Ø¯Ø© ØªØµÙ†ÙŠÙ Ø§Ù„ØµÙÙ‚Ø§Øª Ø§Ù„Ù…ÙˆØ¬ÙˆØ¯Ø© Ø¨Ø§Ø³ØªØ®Ø¯Ø§Ù… Ø§Ù„ØªØµÙ†ÙŠÙ Ø§Ù„Ø±Ø³Ù…ÙŠ"""
    if pwd != ADMIN_PASS: raise HTTPException(403)
    import requests as req_lib
    from bs4 import BeautifulSoup as BS4
    rows = fresh_db().execute("SELECT id, url, objet, description FROM tenders LIMIT 200").fetchall()
    updated = 0
    for row in rows:
        try:
            r = req_lib.get(row['url'], timeout=10, verify=False,
                headers={"User-Agent": random.choice(UAS)})
            if r.status_code == 200:
                soup = BS4(r.text, 'html.parser')
                full = soup.get_text(' ', strip=True)
                raw = extract_official_domain(soup, full)
                domain = normalize_domain(raw)
                if domain:
                    wdb = fresh_db()
                    wdb.execute("UPDATE tenders SET domaine=? WHERE id=?", (domain, row['id']))
                    wdb.commit()
                    wdb.close()
                    updated += 1
            import time as time_lib
            time_lib.sleep(0.5)
        except Exception as e:
            print(f"Reclassify error {row['id']}: {e}")
    return JSONResponse({"updated": updated, "total": len(rows)})

@app.get("/admin/cancel_check")
async def admin_cancel_check(pwd: str=""):
    if pwd != ADMIN_PASS: raise HTTPException(403)
    rows = fresh_db().execute("SELECT id,objet,description FROM tenders WHERE statut='actif' OR statut IS NULL").fetchall()
    updated = 0
    for row in rows:
        if is_cancelled(f"{row['objet']} {row['description'] or ''}"):
            try:
                wdb2 = fresh_db()
                wdb2.execute("UPDATE tenders SET statut='annule' WHERE id=?", (row['id'],))
                wdb2.commit()
                wdb2.close()
                updated += 1
            except: pass
    return JSONResponse({"updated": updated})

@app.get("/api/stats")
async def api_stats():
    return JSONResponse({
        "tenders":     fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='actif' OR statut IS NULL").fetchone()[0],
        "cancelled":   fresh_db().execute("SELECT COUNT(*) FROM tenders WHERE statut='annule'").fetchone()[0],
        "contractors": fresh_db().execute("SELECT COUNT(*) FROM contractors").fetchone()[0],
        "premium":     fresh_db().execute("SELECT COUNT(*) FROM contractors WHERE plan='premium'").fetchone()[0],
    })

