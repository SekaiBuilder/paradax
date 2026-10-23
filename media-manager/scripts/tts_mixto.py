#!/usr/bin/env python3
"""tts_mixto.py — Síntesis de voz con cambio automático de idioma.

Detecta los tramos en japonés (kana/kanji) dentro del guion y los pronuncia
con una voz japonesa nativa (Nanami); el resto lo lee la voz base del idioma
elegido (es=Dalia latina, en=Jenny, it=Elsa). Luego une todos los tramos en
un solo MP3.

Uso:
    tts_mixto.py "<texto>" <es|en|it> <salida.mp3>

Regla para los guiones: las palabras japonesas se escriben en escritura
japonesa (こんにちは皆さん, 漢字) — nunca romanizadas — para que el cambio
de voz se active.
"""
import re
import subprocess
import sys
import tempfile
import os

VOCES = {
    "es": ("es-MX-DaliaNeural", "+6%", "+10Hz"),
    "en": ("en-US-JennyNeural", "+4%", "+8Hz"),
    "it": ("it-IT-ElsaNeural", "+5%", "+8Hz"),
    "ja": ("ja-JP-NanamiNeural", "+2%", "+5Hz"),
}

# Hiragana, katakana (+ extensiones fonéticas y half-width), kanji y
# puntuación/símbolos CJK (。、！？「」・ー etc.)
JA_CHAR = re.compile(r"[぀-ヿㇰ-ㇿ一-鿿･-ﾟ　-〿]")
NEUTRAL = re.compile(r"[\s,.;:!?¡¿…()\"'«»\-—–]+$")


def dividir(texto):
    """Divide el texto en tramos [(idioma, fragmento)] según el alfabeto."""
    tramos = []
    actual_es_ja = None
    actual = ""
    for ch in texto:
        if NEUTRAL.match(ch):
            # Espacios/puntuación neutra: se pegan al tramo en curso.
            actual += ch
            continue
        es_ja = bool(JA_CHAR.match(ch))
        if actual_es_ja is None or es_ja == actual_es_ja:
            actual_es_ja = es_ja if actual_es_ja is None else actual_es_ja
            actual += ch
        else:
            if actual.strip():
                tramos.append((actual_es_ja, actual))
            actual = ch
            actual_es_ja = es_ja
    if actual.strip():
        tramos.append((actual_es_ja, actual))
    return tramos


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    texto, idioma, salida = sys.argv[1], sys.argv[2], sys.argv[3]
    if idioma not in ("es", "en", "it"):
        print(f"Idioma no soportado: {idioma}")
        sys.exit(1)

    edge_tts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..", "local-agent-os", ".venv", "bin", "edge-tts")

    tramos = dividir(texto)
    if not tramos:
        print("Texto vacío")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        piezas = []
        for i, (es_ja, frag) in enumerate(tramos):
            voz, rate, pitch = VOCES["ja"] if es_ja else VOCES[idioma]
            mp3 = os.path.join(tmp, f"seg{i:03d}.mp3")
            for intento in range(3):
                r = subprocess.run(
                    [edge_tts, "--voice", voz, f"--rate={rate}", f"--pitch={pitch}",
                     "--text", frag.strip(), "--write-media", mp3],
                    capture_output=True, text=True,
                )
                if r.returncode == 0 and os.path.getsize(mp3) > 0:
                    break
            else:
                print(f"✗ Falló el tramo {i} ({voz}): {r.stderr.strip()[-200:]}")
                sys.exit(1)
            piezas.append(mp3)

        if len(piezas) == 1:
            subprocess.run(["cp", piezas[0], salida], check=True)
        else:
            # Unir re-codificando (los segmentos pueden diferir en parámetros)
            lista = os.path.join(tmp, "lista.txt")
            with open(lista, "w") as f:
                for p in piezas:
                    f.write(f"file '{p}'\n")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                 "-safe", "0", "-i", lista,
                 "-af", "aresample=24000", "-c:a", "libmp3lame", "-q:a", "3",
                 salida],
                check=True,
            )
    print(f"✓ Voz mixta generada: {salida} ({len(piezas)} tramo(s))")


if __name__ == "__main__":
    main()
