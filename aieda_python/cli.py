#!/usr/bin/env python3
"""
AI-EDA CLI - Interface en ligne de commande pour interagir avec le bridge EasyEDA Pro
Permet de démarrer le serveur WebSocket local ou le serveur REST FastAPI
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ai_eda.cli")

# Import conditionnel pour éviter les erreurs si FastAPI n'est pas installé
try:
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning("FastAPI/uvicorn non détecté → mode REST indisponible")

# Import du serveur WebSocket (à adapter selon ton organisation réelle)
try:
    from aieda_python.bridge_server import start_websocket_server
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.warning("Module bridge_server non trouvé → mode WebSocket indisponible")

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="AI-EDA CLI - Pont entre IA et EasyEDA Pro",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "command",
        choices=["serve", "health", "version"],
        help="Commande à exécuter"
    )

    parser.add_argument(
        "--rest",
        action="store_true",
        help="Démarrer le serveur REST FastAPI au lieu du WebSocket"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Adresse d'écoute (défaut: 127.0.0.1 pour WebSocket local)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port d'écoute (défaut: 8765 pour WebSocket, 8000 pour REST)"
    )

    parser.add_argument(
        "--api-key",
        default=os.getenv("API_KEY", "change-me-please"),
        help="Clé API pour protéger le endpoint REST (env: API_KEY)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation (seulement pour certaines opérations futures)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Activer les logs détaillés"
    )

    return parser.parse_args()


def print_banner(mode: str):
    print("\n" + "="*70)
    print("  AI-EDA Bridge CLI  -  v1.1  (février 2026)")
    print(f"  Mode : {mode}")
    print("="*70 + "\n")


async def run_websocket_server(host: str, port: int):
    if not WEBSOCKET_AVAILABLE:
        logger.error("Le serveur WebSocket n'est pas disponible (module manquant)")
        sys.exit(1)

    print_banner("WebSocket local")
    logger.info(f"Démarrage WebSocket server → ws://{host}:{port}")
    logger.info("Connecte-toi depuis EasyEDA Pro → AI EDA > Start Bridge")

    await start_websocket_server(host=host, port=port)


def run_rest_server(host: str, port: int, api_key: str):
    if not FASTAPI_AVAILABLE:
        logger.error("FastAPI/uvicorn non installé → impossible de lancer le mode REST")
        logger.info("Installez les dépendances : pip install fastapi uvicorn")
        sys.exit(1)

    # On définit la variable d'environnement pour que main.py la récupère
    os.environ["API_KEY"] = api_key

    print_banner("FastAPI REST (compatible GPT Actions)")
    logger.info(f"Démarrage REST server → http://{host}:{port}")
    logger.info(f"Clé API requise : {api_key}")
    logger.info("Endpoints principaux :")
    logger.info("  GET  /health")
    logger.info("  POST /schematic/patch")
    logger.info("  GET  /openapi.yaml")

    # Lancement via uvicorn
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level="info" if not args.verbose else "debug",
        factory=False
    )


def main():
    global args
    args = parse_arguments()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.command == "version":
        print("AI-EDA CLI v1.1 (2026-02)")
        print("WebSocket support :", "Oui" if WEBSOCKET_AVAILABLE else "Non")
        print("REST/FastAPI support :", "Oui" if FASTAPI_AVAILABLE else "Non")
        return

    if args.command == "health":
        print('{"ok": true, "service": "ai_eda_bridge", "cli": "running"}')
        return

    if args.command == "serve":
        host = "0.0.0.0" if args.rest else args.host
        port = args.port if args.rest else args.port  # 8000 par défaut pour REST

        if args.rest:
            run_rest_server(host, port, args.api_key)
        else:
            # Mode WebSocket (asynchrone)
            try:
                asyncio.run(run_websocket_server(args.host, args.port))
            except KeyboardInterrupt:
                logger.info("Arrêt du serveur WebSocket par l'utilisateur")
            except Exception as e:
                logger.error(f"Erreur lors du démarrage WebSocket : {e}")
                sys.exit(1)
    else:
        print("Commande inconnue. Utilisation : ai_eda serve [--rest] [--verbose]")
        sys.exit(1)


if __name__ == "__main__":
    main()
