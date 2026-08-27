# Cómo ponerlo en tu perfil

Dos tarjetas SVG animadas (`dark_mode.svg` / `light_mode.svg` y `top_dark.svg` / `top_light.svg`)
y una GitHub Action que las regenera a diario con tus números reales.

## Flujo

```
foto.jpg ──cutout.py──▶ subject.png ──ascii_art.py──▶ ascii.json ─┐
profile.json (tu contenido) ──────────────────────────────────────┼──build_svg.py──▶ 4 SVG
GitHub API ──update_stats.py──▶ stats.json ───────────────────────┘
```

## 1. El repo especial de perfil

Crea un repo **público** llamado exactamente como tu usuario (`tu-usuario/tu-usuario`);
GitHub muestra su `README.md` arriba de tu perfil. Copia aquí todos estos archivos, incluida
la carpeta oculta `.github/`.

## 2. Tu foto → ASCII a color

```bash
pip install -r requirements.txt -r requirements-photo.txt
python cutout.py mi_foto.jpg --crop x0,y0,x1,y1 -o subject.png   # recorta cabeza+hombros y quita el fondo
python ascii_art.py subject.png --cut-dark 10 --cols 52 --rows 28 --floor 55
```

`cutout.py` usa GrabCut para separar a la persona del fondo (con fondo liso funciona muy bien) y
lo pinta de negro; `ascii_art.py` genera `ascii.json` (caracteres + color por celda para ambos
temas) y `ascii.txt` para verlo rápido. Los parámetros de arriba son los que quedaron bien con la
foto actual; `subject.png` está en `.gitignore` para que la foto no se suba al repo.

| Opción | Para qué |
|---|---|
| `--cols 52 --rows 28` | Tamaño máximo del arte. |
| `--cut-dark N` | Convierte en espacio los pixeles más oscuros que N (0–255): borra el fondo negro que dejó `cutout.py`. |
| `--cut-light N` | Lo mismo para fondos blancos. |
| `--floor N` | Nivel mínimo de la persona: con 55 el pelo oscuro sigue dibujándose como puntos en vez de desaparecer. |
| `--gamma 0.8` | Aclara medios tonos (`> 1` los oscurece). |
| `--colors 64` | Tamaño de la paleta (menos colores = SVG más ligero). `--mono` para un solo tono. |
| `--ramp long` | Paleta de 70 caracteres en vez de 10 (más detalle, menos legible de lejos). |
| `--sketch` / `--sketch-light` | Los pixeles oscuros reciben los glifos densos (look de dibujo a lápiz), en las dos tarjetas o solo en la clara. |

## 3. Tu contenido: `profile.json`

- `user` / `host`: el prompt (`mayra-moncayo@clip`).
- `uptime_since`: `"YYYY-MM-DD"`; `null` usa la antigüedad de tu cuenta de GitHub.
- `boot`: las líneas del arranque, en orden.
- `lines`: la ficha. `"Clave: valor"` → `- Clave: ..... valor`; dos espacios al inicio = un
  nivel de sangría; una línea sin `": "` es encabezado de sección; `""` línea vacía;
  `"{stats}"` inserta el bloque de GitHub Stats.
- `languages.max` / `languages.exclude`: cuántos lenguajes muestra la barra y cuáles ignora.
- `top`: los procesos de la segunda tarjeta (`stat` R/S, `cpu`, `time`, `cmd`).

```bash
python build_svg.py   # regenera los 4 SVG; ábrelos en el navegador para ver la animación
```

`stats.json` trae números de ejemplo para que todo renderice antes de la primera corrida;
el workflow lo sobreescribe.

## 4. Token y Action

1. GitHub → Settings → Developer settings → Personal access tokens → **Tokens (classic)** →
   scopes `repo` y `read:user` (`read:org` si quieres contar repos de organizaciones).
2. En el repo: Settings → Secrets and variables → Actions → **New repository secret**
   llamado `ACCESS_TOKEN`.
3. Push a `main` (si tu rama se llama distinto, cámbiala en `.github/workflows/update-profile.yml`).

El workflow corre cuando cambias `profile.json`, `ascii.json` o los scripts; a mano desde la
pestaña Actions ("Run workflow"); y a diario a las 00:17 hora de Ciudad de México.

## Notas

- **Animación.** Es CSS dentro del SVG: el navegador la reproduce aunque GitHub sirva la
  imagen como `<img>`. Se ve una vez por carga (~4 s). Con `prefers-reduced-motion` se
  muestra la tarjeta terminada sin animación.
- **Alineación entre fuentes.** Cada línea lleva `textLength`, así que la retícula se mantiene
  aunque el visitante tenga Consolas, Menlo o DejaVu.
- `LOC_AFFILIATIONS` (en el workflow) controla qué repos entran al conteo de líneas y a la
  barra de lenguajes. Por defecto solo los tuyos (`OWNER`); agrega
  `COLLABORATOR,ORGANIZATION_MEMBER` para incluir los de la empresa. La primera corrida recorre
  todo tu historial (puede tardar varios minutos); las siguientes son incrementales gracias a
  `cache/loc.json`, cuyas llaves son hashes para no exponer nombres de repos privados.
  `EXCLUDE_REPOS=owner/repo,...` salta repos concretos.
- "Commits" usa el mismo conteo que la gráfica de contribuciones de GitHub; "Repos" son los
  tuyos y "Contributed" los ajenos con commits/PRs/issues tuyos. `load average` en `top` son
  tus contribuciones de 1, 7 y 30 días.
- GitHub cachea las imágenes de los README: los cambios tardan unos minutos en verse.
- Si el cambio de tema claro/oscuro no funciona con rutas relativas, usa la URL completa:
  `https://raw.githubusercontent.com/TU-USUARIO/TU-USUARIO/main/dark_mode.svg`.
