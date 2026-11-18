"""
Genera las imágenes de los 3 diagramas a partir de sus fuentes HTML (en 3. Documentación/img/):

    diagrama_ER_source.html      -> img/diagrama_ER_fleetlogix.png    (Avance 1)
    modelo_estrella_source.html  -> img/modelo_estrella.png           (Avance 3)
    aws_diagram_source.html      -> 2. Scripts/aws_architecture_diagram.png (Avance 4)

Usa Google Chrome en modo headless para sacar una captura de cada página. El diagrama ER usa
Mermaid desde un CDN, así que ese necesita internet.

Uso:  python "3. Documentación/generadores/generar_diagramas.py"
      (si Chrome no está en la ruta de Mac, indicarla con la variable CHROME)
"""
import os
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
IMG = RAIZ / '3. Documentación' / 'img'
CHROME = os.getenv('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# fuente, salida, ancho y alto de la página (px), escala de la imagen
DIAGRAMAS = [
    (IMG / 'diagrama_ER_source.html', IMG / 'diagrama_ER_fleetlogix.png', 1233, 1019, 2),
    (IMG / 'modelo_estrella_source.html', IMG / 'modelo_estrella.png', 1400, 930, 1.5),
    (IMG / 'aws_diagram_source.html', RAIZ / '2. Scripts' / 'aws_architecture_diagram.png', 1600, 1010, 1.5),
]

for fuente, salida, ancho, alto, escala in DIAGRAMAS:
    subprocess.run([CHROME, '--headless=new', '--hide-scrollbars', f'--window-size={ancho},{alto}',
                    f'--force-device-scale-factor={escala}', '--virtual-time-budget=15000',   # espera a que Mermaid dibuje
                    f'--screenshot={salida}', fuente.as_uri()],
                   check=True, capture_output=True)
    print('OK', salida.relative_to(RAIZ))
