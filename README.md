# Logros de GitHub

Guía y script para conseguir los logros del perfil de GitHub. El script solo actúa en **tu cuenta** y en un repositorio de práctica (`logros-github`). No crea cuentas extra, no pone estrellas falsas y no toca repositorios de otras personas.

Los logros pueden tardar **varias horas** (a veces hasta un día) en aparecer en el perfil.

GitHub tiene siete logros que todavía se pueden ganar. Tres se completan solos con este script. El resto pide a otra persona, estrellas reales o un pago. Otros cinco existieron o son internos y no se pueden conseguir.

## Los que automatiza este script

| Logro | Qué lo desbloquea | Niveles | Comando |
| --- | --- | --- | --- |
| Quickdraw | Cierras un issue o una pull request antes de 5 minutos | solo uno | `quickdraw` o `rapidos` |
| YOLO | Fusionas tu propia pull request sin pedir revisión | solo uno | `yolo` o `rapidos` |
| Pull Shark | Pull requests tuyas que terminan fusionadas | 2, 16, 128, 1024 | `pull-shark` |

`rapidos` hace los tres del nivel base: Quickdraw, YOLO y Pull Shark con 2 pull requests. Esas fusiones cuentan en toda la cuenta, no solo en este repositorio. La primera pull request fusionada sin revisión también cubre YOLO, así que no hace falta repetirla.

## Los que se pueden conseguir, pero no automatizar

Estos cuatro siguen activos. El script no los completa porque dependen de otra persona o de dinero.

### Pair Extraordinaire

Un commit de una pull request fusionada lleva `Co-authored-by` de **otra cuenta real de GitHub**. Los niveles son 1, 10, 24 y 48.

La otra persona tiene que estar de acuerdo: el commit queda a su nombre y también puede recibir el logro. Una segunda cuenta tuya va contra las normas de GitHub.

Si ya tienes a esa persona, el script solo escribe el trailer y fusiona:

```bash
python3 logros.py pair --con USUARIO_DE_TU_AMIGO
python3 logros.py pair --con USUARIO_DE_TU_AMIGO --nivel bronce
```

También vale el correo noreply de esa cuenta:

```bash
python3 logros.py pair --coautor "Ada Lovelace <12345+ada@users.noreply.github.com>"
```

Esas pull requests también suman para Pull Shark.

### Galaxy Brain

Alguien marca como aceptadas tus respuestas en las discusiones de un repositorio **público** (no hace falta que sea el foro de GitHub Community). No cuenta si marcas tu propia respuesta. Los niveles son 2, 8, 16 y 32.

```bash
python3 logros.py galaxy
```

Eso deja el repositorio público, activa Discussions y muestra el enlace para que la otra persona abra la pregunta. Cuando la haya abierto:

```bash
python3 logros.py galaxy --responder
```

Luego esa persona pulsa «Marcar como respuesta» en tu comentario.

### Starstruck

Un repositorio que hayas creado recibe estrellas de otras personas. Los niveles son 16, 128, 512 y 4096. No hay forma legítima de automatizarlo: hacen falta estrellas reales.

### Public Sponsor

Patrocinas en público a una persona, un repositorio o una organización con [GitHub Sponsors](https://github.com/sponsors). El importe lo eliges tú al pagar. El script no gasta dinero.

## Los que no se pueden conseguir

| Logro | Por qué |
| --- | --- |
| Heart On Your Sleeve | Logro de prueba (reaccionar con un corazón). GitHub lo activó un momento y lo retiró. |
| Open Sourcerer | Logro de prueba (pull requests fusionadas en varios repositorios públicos). También retirado. |
| Arctic Code Vault Contributor | Solo quien tenía código en el archivo de febrero de 2020. |
| Mars 2020 Helicopter Contributor | Solo quien contribuyó a los repositorios que volaron con Ingenuity. |
| Proxima Pioneer, Proxima Staffshipper, Proxima Staffuser | Logros internos del personal de GitHub. |

## Preparación

Hace falta Python 3.9 o superior. No hay dependencias externas.

1. Crea un token clásico **solo** con el alcance `repo`:
   [nuevo token](https://github.com/settings/tokens/new?scopes=repo&description=logros-github)
2. Copia el ejemplo y pega el token:

```bash
cp .env.example .env
```

```
GITHUB_TOKEN=ghp_tu_token
REPO_NAME=logros-github
```

`.env` está en `.gitignore`. No lo subas. Cuando termines, revoca el token en GitHub.

Si ya usas GitHub CLI (`gh auth login`), el script usa ese token cuando `GITHUB_TOKEN` no está definido.

## Uso

```bash
python3 logros.py quien
python3 logros.py preparar
python3 logros.py rapidos
```

Subir Pull Shark:

```bash
python3 logros.py pull-shark --nivel bronce    # 16
python3 logros.py pull-shark --nivel plata     # 128
python3 logros.py pull-shark --nivel oro --confirmar   # 1024
```

Ver el avance, la lista de logros y borrar el repositorio de práctica:

```bash
python3 logros.py estado
python3 logros.py guia
python3 logros.py borrar --si
```

`borrar` solo elimina `logros-github` si lo creó esta herramienta, no tiene estrellas y no tiene forks. `--simular` en cualquier comando muestra el plan sin escribir en GitHub.

A partir de 33 pull requests nuevas el script pide `--confirmar`: GitHub limita el ritmo y el nivel oro puede tardar alrededor de una hora.

## Dónde se ven

En el perfil, en la barra lateral, debajo de la biografía. Se pueden ocultar uno a uno en **Settings → Public profile → Show Achievements on my profile**.
