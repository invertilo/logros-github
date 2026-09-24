#!/usr/bin/env python3
"""Desbloquea logros del perfil de GitHub en un repositorio de tu cuenta."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".logros-estado.json"
ENV_PATH = ROOT / ".env"
API = "https://api.github.com"
MARKER = "LOGROS.md"
BRANCH_PREFIX = "logro-"
CONFIRMAR_DESDE = 33

NIVEL_PULL = {"base": 2, "bronce": 16, "plata": 128, "oro": 1024}
NIVEL_PAIR = {"base": 1, "bronce": 10, "plata": 24, "oro": 48}
NIVEL_GALAXY = {"base": 2, "bronce": 8, "plata": 16, "oro": 32}

COAUTOR_RE = re.compile(r"^[^<>\n]+ <[^<>\s@]+@[^<>\s]+>$")


class GitHubError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def load_env():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def token_from_gh():
    try:
        out = subprocess.check_output(
            ["gh", "auth", "token"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
    return out


def get_token():
    load_env()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or token_from_gh()
    if not token:
        raise SystemExit(
            "Falta el token.\n"
            "Crea uno con alcance repo:\n"
            "  https://github.com/settings/tokens/new?scopes=repo&description=logros-github\n"
            "Guárdalo en .env como GITHUB_TOKEN=... y no lo subas a ningún sitio."
        )
    return token


def repo_name():
    load_env()
    name = os.environ.get("REPO_NAME", "logros-github").strip() or "logros-github"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SystemExit("REPO_NAME solo puede tener letras, números, punto, guion y guion bajo.")
    return name


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Client:
    def __init__(self, token):
        self.token = token
        self.headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "logros-github",
            "Content-Type": "application/json",
        }

    def request(self, method, path, body=None, query=None, retries=6):
        url = API + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        last_error = None
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw) if raw else None
                    return response.status, response.headers, parsed
            except urllib.error.HTTPError as error:
                raw = error.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"message": raw[:300]}
                message = parsed.get("message") or raw[:300] or error.reason
                detail = parsed.get("errors")
                if detail:
                    message = message + " " + json.dumps(detail, ensure_ascii=False)
                last_error = GitHubError(error.code, "GitHub respondió {0}: {1}".format(error.code, message))
                secondary = "rate limit" in message.lower() or error.code in (403, 429)
                if secondary or error.code >= 500:
                    wait = 20 * (attempt + 1)
                    print("  límite o error temporal, espero {0}s".format(wait), flush=True)
                    time.sleep(wait)
                    continue
                raise last_error
            except urllib.error.URLError as error:
                last_error = GitHubError(0, "No pude conectar con GitHub: {0}".format(error.reason))
                time.sleep(3 * (attempt + 1))
        raise last_error

    def get(self, path, query=None):
        return self.request("GET", path, query=query)[2]

    def post(self, path, body):
        return self.request("POST", path, body)[2]

    def put(self, path, body):
        return self.request("PUT", path, body)[2]

    def patch(self, path, body):
        return self.request("PATCH", path, body)[2]

    def delete(self, path):
        self.request("DELETE", path)


def me(client):
    user = client.get("/user")
    scopes = ""
    # Una llamada ligera para leer el alcance del token clásico.
    try:
        status_headers = client.request("GET", "/user")[1]
        scopes = status_headers.get("X-OAuth-Scopes") or ""
    except GitHubError:
        scopes = ""
    return user, scopes


def full_name(login):
    return login + "/" + repo_name()


def get_repo(client, login):
    try:
        return client.get("/repos/" + full_name(login))
    except GitHubError as error:
        if error.status == 404:
            return None
        raise


def require_marker(client, login):
    repo = get_repo(client, login)
    if repo is None:
        raise SystemExit("Todavía no existe el repositorio. Ejecuta: python3 logros.py preparar")
    try:
        client.get("/repos/" + full_name(login) + "/contents/" + MARKER)
    except GitHubError as error:
        if error.status == 404:
            raise SystemExit(
                "Este repositorio no tiene {0}, así que no lo toco.\n"
                "Si es el repo de los logros, ejecuta: python3 logros.py preparar --usar-este".format(MARKER)
            )
        raise
    return repo


def ensure_repo(client, login, privado, usar_este):
    name = repo_name()
    repo = get_repo(client, login)
    if repo is None:
        print("Creo el repositorio {0}/{1}".format(login, name), flush=True)
        repo = client.post(
            "/user/repos",
            {
                "name": name,
                "description": "Repositorio creado por logros.py para los logros del perfil. Se puede borrar.",
                "private": privado,
                "auto_init": True,
                "has_issues": True,
                "has_discussions": True,
            },
        )
        wait_for_branch(client, login, repo["default_branch"])
    else:
        commits = repo.get("size", 0)
        has_marker = True
        try:
            client.get("/repos/" + full_name(login) + "/contents/" + MARKER)
        except GitHubError as error:
            has_marker = error.status != 404
            if error.status not in (404,):
                raise
        marcado = has_marker or "logros.py" in (repo.get("description") or "")
        if not marcado and not usar_este and (repo.get("stargazers_count") or commits):
            raise SystemExit(
                "Ya existe {0} y no parece un repo de esta herramienta.\n"
                "Usa otro REPO_NAME o, si de verdad quieres usarlo: python3 logros.py preparar --usar-este".format(
                    repo["full_name"]
                )
            )
        changes = {}
        if not repo.get("has_issues"):
            changes["has_issues"] = True
        if not repo.get("has_discussions"):
            changes["has_discussions"] = True
        if privado is False and repo.get("private"):
            changes["private"] = False
        if changes:
            repo = client.patch("/repos/" + repo["full_name"], changes)
        print("Uso el repositorio {0}".format(repo["full_name"]), flush=True)

    write_file(
        client,
        repo,
        MARKER,
        "Repositorio de practica para los logros del perfil de GitHub.\n",
        "Añade la marca de logros.py",
        repo["default_branch"],
    )
    state = load_state()
    state["repo"] = repo["full_name"]
    save_state(state)
    print("Listo: https://github.com/{0}".format(repo["full_name"]), flush=True)
    return repo


def wait_for_branch(client, login, branch):
    path = "/repos/{0}/git/ref/heads/{1}".format(full_name(login), branch)
    for _ in range(15):
        try:
            return client.get(path)
        except GitHubError as error:
            if error.status != 404:
                raise
            time.sleep(1)
    raise SystemExit("El repositorio se creó, pero la rama por defecto aún no aparece. Vuelve a intentar.")


def write_file(client, repo, path, text, message, branch):
    body = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    try:
        existing = client.get(
            "/repos/{0}/contents/{1}".format(repo["full_name"], path),
            {"ref": branch},
        )
        if isinstance(existing, dict) and existing.get("sha"):
            body["sha"] = existing["sha"]
    except GitHubError as error:
        if error.status != 404:
            raise
    return client.put("/repos/{0}/contents/{1}".format(repo["full_name"], path), body)


def head_sha(client, repo):
    ref = client.get("/repos/{0}/git/ref/heads/{1}".format(repo["full_name"], repo["default_branch"]))
    return ref["object"]["sha"]


def merge_pr(client, repo, number):
    path = "/repos/{0}/pulls/{1}/merge".format(repo["full_name"], number)
    last = None
    for _ in range(8):
        try:
            return client.put(path, {"merge_method": "merge"})
        except GitHubError as error:
            last = error
            if error.status in (405, 409):
                time.sleep(2)
                continue
            raise
    raise last


def cerrar_prs_pendientes(client, repo, login):
    pulls = client.get("/repos/{0}/pulls".format(repo["full_name"]), {"state": "open", "per_page": 100})
    closed = 0
    for pull in pulls:
        ref = pull["head"]["ref"]
        author = pull["user"]["login"]
        if author != login or not ref.startswith(BRANCH_PREFIX):
            continue
        print("  fusiono la pull request pendiente #{0}".format(pull["number"]), flush=True)
        merge_pr(client, repo, pull["number"])
        delete_branch(client, repo, ref)
        closed += 1
    return closed


def delete_branch(client, repo, branch):
    if not branch.startswith(BRANCH_PREFIX):
        return
    try:
        client.delete("/repos/{0}/git/refs/heads/{1}".format(repo["full_name"], urllib.parse.quote(branch)))
    except GitHubError as error:
        if error.status != 404 and error.status != 422:
            print("  no pude borrar la rama {0}: {1}".format(branch, error), flush=True)


def crear_pr(client, repo, login, numero, coautor):
    branch = "{0}{1}-{2}".format(BRANCH_PREFIX, int(time.time()), numero)
    sha = head_sha(client, repo)
    client.post(
        "/repos/{0}/git/refs".format(repo["full_name"]),
        {"ref": "refs/heads/" + branch, "sha": sha},
    )
    filename = "aportes/aporte-{0}.md".format(branch)
    message = "Añade el aporte {0}".format(numero)
    body = "Pull request creada con logros.py para los logros del perfil.\n"
    if coautor:
        message = message + "\n\nCo-authored-by: " + coautor
        body = body + "\nCo-authored-by: " + coautor + "\n"
    write_file(
        client,
        repo,
        filename,
        "Aporte {0} de {1}.\n".format(numero, login),
        message,
        branch,
    )
    pull = client.post(
        "/repos/{0}/pulls".format(repo["full_name"]),
        {
            "title": "Aporte {0}".format(numero),
            "head": branch,
            "base": repo["default_branch"],
            "body": body,
        },
    )
    merge_pr(client, repo, pull["number"])
    delete_branch(client, repo, branch)
    return pull["number"]


def buscar_total(client, query):
    data = client.get("/search/issues", {"q": query, "per_page": 1})
    return int(data.get("total_count") or 0)


def pull_requests_fusionadas(client, login):
    return buscar_total(client, "is:pr is:merged author:" + login)


def coautores_vistos(client, login):
    return buscar_total(client, 'is:pr is:merged author:{0} "Co-authored-by"'.format(login))


def pedir_volumen(nuevas, confirmar):
    if nuevas >= CONFIRMAR_DESDE and not confirmar:
        raise SystemExit(
            "Eso crea {0} pull requests nuevas. Puede tardar y GitHub limita el ritmo.\n"
            "Si quieres seguir, repite el comando con --confirmar.".format(nuevas)
        )


def crear_varias(client, login, cantidad, coautor, clave_estado):
    repo = require_marker(client, login)
    recuperadas = cerrar_prs_pendientes(client, repo, login)
    if recuperadas:
        print("Fusioné {0} pull requests que se habían quedado abiertas.".format(recuperadas), flush=True)
    state = load_state()
    for i in range(1, cantidad + 1):
        numero = int(state.get(clave_estado, 0)) + 1
        print("[{0}/{1}] creo y fusiono una pull request".format(i, cantidad), flush=True)
        number = crear_pr(client, repo, login, numero, coautor)
        state[clave_estado] = numero
        if clave_estado != "pull_shark_seen":
            state["pull_shark_seen"] = int(state.get("pull_shark_seen", 0)) + 1
        state["repo"] = repo["full_name"]
        save_state(state)
        print("  pull request #{0} fusionada".format(number), flush=True)
        if i != cantidad:
            time.sleep(2)
    return cantidad


def resolver_coautor(client, usuario, trailer):
    if trailer:
        trailer = trailer.strip()
        if not COAUTOR_RE.match(trailer):
            raise SystemExit('El coautor tiene que verse así: Nombre <correo@ejemplo.com>')
        return trailer
    if not usuario:
        raise SystemExit("Indica la otra persona con --con USUARIO o con --coautor \"Nombre <correo>\".")
    try:
        user = client.get("/users/" + urllib.parse.quote(usuario))
    except GitHubError as error:
        if error.status == 404:
            raise SystemExit("No existe el usuario de GitHub {0}.".format(usuario))
        raise
    name = user.get("name") or user["login"]
    email = "{0}+{1}@users.noreply.github.com".format(user["id"], user["login"])
    return "{0} <{1}>".format(name, email)


def cantidad_objetivo(args, niveles, remoto, vistos):
    if args.cantidad is not None and (args.hasta is not None or args.nivel):
        raise SystemExit("Usa solo uno: --cantidad, o --hasta, o --nivel.")
    if args.cantidad is not None:
        if args.cantidad < 1:
            raise SystemExit("--cantidad tiene que ser 1 o más.")
        return args.cantidad
    if args.nivel:
        if args.nivel not in niveles:
            raise SystemExit("Nivel desconocido. Usa base, bronce, plata u oro.")
        objetivo = niveles[args.nivel]
    elif args.hasta is not None:
        objetivo = args.hasta
    else:
        objetivo = niveles["base"]
    base = max(remoto, vistos)
    return max(0, objetivo - base)


def cmd_quien(client, _args):
    user, scopes = me(client)
    print("Cuenta: {0}".format(user["login"]))
    print("Perfil: https://github.com/{0}".format(user["login"]))
    if scopes:
        print("Alcances del token: {0}".format(scopes))
        parts = [part.strip() for part in scopes.split(",")]
        if "repo" not in parts:
            print("Este token no tiene el alcance repo. Los comandos de escritura van a fallar.")
    else:
        print("No veo los alcances (normal en un token fino). Hace falta permiso de contenidos, issues y pull requests.")


def cmd_preparar(client, args):
    user, _scopes = me(client)
    ensure_repo(client, user["login"], args.privado, args.usar_este)


def cmd_quickdraw(client, args):
    user, _scopes = me(client)
    if args.simular:
        print("Abriría un issue en {0} y lo cerraría al momento.".format(full_name(user["login"])))
        return
    repo = require_marker(client, user["login"])
    started = time.time()
    issue = client.post(
        "/repos/{0}/issues".format(repo["full_name"]),
        {
            "title": "Cierre rápido para Quickdraw",
            "body": "Issue abierto y cerrado por logros.py en menos de cinco minutos.",
        },
    )
    client.patch("/repos/{0}/issues/{1}".format(repo["full_name"], issue["number"]), {"state": "closed"})
    elapsed = time.time() - started
    state = load_state()
    state["quickdraw"] = True
    state["repo"] = repo["full_name"]
    save_state(state)
    print("Quickdraw: issue #{0} cerrado en {1:.1f}s.".format(issue["number"], elapsed))
    print("El logro puede tardar unas horas en salir en https://github.com/{0}".format(user["login"]))


def cmd_pull_shark(client, args):
    user, _scopes = me(client)
    login = user["login"]
    state = load_state()
    remoto = 0 if args.simular else pull_requests_fusionadas(client, login)
    nuevas = cantidad_objetivo(args, NIVEL_PULL, remoto, int(state.get("pull_shark_seen", 0)))
    if args.simular:
        print("Crearía {0} pull requests fusionadas en {1}.".format(nuevas, full_name(login)))
        print("GitHub cuenta ahora unas {0} pull requests fusionadas tuyas.".format(remoto))
        return
    if nuevas == 0:
        print("Pull Shark: ya estás en ese nivel o por encima ({0} fusionadas según GitHub).".format(remoto))
        return
    pedir_volumen(nuevas, args.confirmar)
    print("GitHub ve {0} pull requests fusionadas. Creo {1} más.".format(remoto, nuevas), flush=True)
    crear_varias(client, login, nuevas, None, "pull_shark_seen")
    print("Listo. La primera pull request fusionada sin revisión también cubre YOLO.")
    print("El logro puede tardar unas horas: https://github.com/{0}".format(login))


def cmd_yolo(client, args):
    args.cantidad = 1
    args.hasta = None
    args.nivel = None
    print("YOLO es fusionar tu pull request sin pedir revisión. Creo una.", flush=True)
    cmd_pull_shark(client, args)


def cmd_pair(client, args):
    user, _scopes = me(client)
    login = user["login"]
    if args.con and args.con.lower() == login.lower():
        raise SystemExit("Pair Extraordinaire necesita otra cuenta real, no la tuya.")
    coautor = None if args.simular and not (args.con or args.coautor) else resolver_coautor(client, args.con, args.coautor)
    if coautor and login.lower() in coautor.lower():
        raise SystemExit("Ese coautor parece tu propia cuenta. Tiene que ser otra persona.")
    state = load_state()
    remoto = 0 if args.simular else coautores_vistos(client, login)
    nuevas = cantidad_objetivo(args, NIVEL_PAIR, remoto, int(state.get("pair_seen", 0)))
    if args.simular:
        print("Crearía {0} pull requests con coautor en {1}.".format(nuevas, full_name(login)))
        return
    print("Estas pull requests atribuyen los commits a: {0}".format(coautor))
    print("Esa persona verá el commit. Úsalo solo si está de acuerdo.")
    if nuevas == 0:
        print("Pair Extraordinaire: el contador local ya llega a ese nivel.")
        return
    pedir_volumen(nuevas, args.confirmar)
    crear_varias(client, login, nuevas, coautor, "pair_seen")
    print("Esas fusiones también suman para Pull Shark, y la primera sin revisión cubre YOLO.")
    print("El logro puede tardar unas horas: https://github.com/{0}".format(login))


def cmd_rapidos(client, args):
    user, _scopes = me(client)
    if args.simular:
        print("Haría Quickdraw y las pull requests que falten para Pull Shark base (2).")
        if args.con or args.coautor:
            print("Una de ellas llevaría coautor para Pair Extraordinaire.")
        return
    cmd_quickdraw(client, args)
    if args.con or args.coautor:
        pair_args = argparse.Namespace(**vars(args))
        pair_args.cantidad = None
        pair_args.hasta = 1
        pair_args.nivel = None
        pair_args.confirmar = True
        pair_args.simular = False
        cmd_pair(client, pair_args)
    shark = argparse.Namespace(**vars(args))
    shark.cantidad = None
    shark.hasta = 2
    shark.nivel = None
    shark.confirmar = True
    shark.simular = False
    cmd_pull_shark(client, shark)


def discussion_categories(client, repo):
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        discussionCategories(first: 20) {
          nodes { id name slug isAnswerable }
        }
      }
    }
    """
    owner, name = repo["full_name"].split("/", 1)
    data = client.post("/graphql", {"query": query, "variables": {"owner": owner, "name": name}})
    if data.get("errors"):
        raise GitHubError(200, json.dumps(data["errors"], ensure_ascii=False))
    nodes = data["data"]["repository"]["discussionCategories"]["nodes"]
    return nodes


def esperar_categoria(client, repo):
    for _ in range(10):
        nodes = discussion_categories(client, repo)
        for node in nodes:
            if node.get("isAnswerable"):
                return node
        time.sleep(2)
    return None


def cmd_galaxy(client, args):
    user, _scopes = me(client)
    login = user["login"]
    if args.simular:
        print("Activaría Discussions y te diría cómo conseguir respuestas aceptadas.")
        return
    repo = require_marker(client, login)
    if repo.get("private"):
        print("Galaxy Brain pide un repositorio público. Lo paso a público.", flush=True)
        repo = client.patch("/repos/" + repo["full_name"], {"private": False})
    if not repo.get("has_discussions"):
        repo = client.patch("/repos/" + repo["full_name"], {"has_discussions": True})
    categoria = esperar_categoria(client, repo)
    if categoria is None:
        raise SystemExit("Discussions aún no tiene una categoría de preguntas. Espera un minuto y vuelve a ejecutar galaxy.")

    if args.responder:
        responder_discusiones(client, repo, login)
        return

    url = "https://github.com/{0}/discussions/new?category={1}".format(repo["full_name"], categoria["slug"])
    print("Galaxy Brain no se desbloquea con una respuesta que tú mismo marques.")
    print("Hace falta que otra persona abra la pregunta y marque tu respuesta.")
    print("")
    print("Pídele que entre aquí, con su cuenta, y publique una pregunta real:")
    print("  " + url)
    print("Luego ejecuta:")
    print("  python3 logros.py galaxy --responder")
    print("Y que esa persona pulse «Marcar como respuesta» en tu comentario.")
    print("")
    print("Niveles: 2 (base), 8 (bronce), 16 (plata), 32 (oro).")
    print("Perfil: https://github.com/{0}".format(login))


def responder_discusiones(client, repo, login):
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        discussions(first: 50, states: OPEN) {
          nodes {
            id
            number
            title
            url
            isAnswered
            author { login }
            category { isAnswerable }
          }
        }
      }
    }
    """
    owner, name = repo["full_name"].split("/", 1)
    data = client.post("/graphql", {"query": query, "variables": {"owner": owner, "name": name}})
    if data.get("errors"):
        raise GitHubError(200, json.dumps(data["errors"], ensure_ascii=False))
    nodes = data["data"]["repository"]["discussions"]["nodes"]
    pendientes = []
    for node in nodes:
        author = (node.get("author") or {}).get("login")
        category = node.get("category") or {}
        if node.get("isAnswered"):
            continue
        if not category.get("isAnswerable"):
            continue
        if author == login:
            continue
        pendientes.append(node)
    if not pendientes:
        print("No hay preguntas de otra persona sin respuesta en este repositorio.")
        print("La otra cuenta tiene que abrirlas antes, con: python3 logros.py galaxy")
        return
    mutation = """
    mutation($id: ID!, $body: String!) {
      addDiscussionComment(input: {discussionId: $id, body: $body}) {
        comment { url }
      }
    }
    """
    state = load_state()
    hechos = state.get("galaxy_urls", [])
    for node in pendientes:
        body = (
            "Respuesta publicada con logros.py.\n\n"
            "Quien abrió «{0}» puede marcar este comentario como respuesta. "
            "Eso es lo que cuenta para Galaxy Brain."
        ).format(node["title"])
        result = client.post(
            "/graphql",
            {"query": mutation, "variables": {"id": node["id"], "body": body}},
        )
        if result.get("errors"):
            print("No pude responder #{0}: {1}".format(node["number"], result["errors"]))
            continue
        url = result["data"]["addDiscussionComment"]["comment"]["url"]
        hechos.append(url)
        print("Respuesta publicada: {0}".format(url))
    state["galaxy_urls"] = hechos
    state["repo"] = repo["full_name"]
    save_state(state)
    print("Falta que el autor de cada pregunta la marque como respuesta.")


def cmd_estado(client, _args):
    user, _scopes = me(client)
    login = user["login"]
    state = load_state()
    print("Cuenta: https://github.com/{0}".format(login))
    repo = get_repo(client, login)
    if repo:
        print("Repositorio: https://github.com/{0}".format(repo["full_name"]))
    else:
        print("Repositorio: todavía no existe. Ejecuta python3 logros.py preparar")
    try:
        print("Pull requests fusionadas en tu cuenta: {0}".format(pull_requests_fusionadas(client, login)))
    except GitHubError as error:
        print("No pude contar las pull requests: {0}".format(error))
    print("Quickdraw hecho por este script: {0}".format("sí" if state.get("quickdraw") else "aún no"))
    print("Pull requests creadas aquí (contador local): {0}".format(state.get("pull_shark_seen", 0)))
    print("Pull requests con coautor creadas aquí: {0}".format(state.get("pair_seen", 0)))
    print("Respuestas de Galaxy Brain publicadas aquí: {0}".format(len(state.get("galaxy_urls", []))))
    print("Niveles Pull Shark: 2, 16, 128, 1024")
    print("Niveles Pair Extraordinaire: 1, 10, 24, 48")
    print("Niveles Galaxy Brain: 2, 8, 16, 32")


def cmd_guia(_client, _args):
    print("Automatizable en tu cuenta")
    print("  Quickdraw            cerrar un issue en menos de 5 minutos")
    print("  YOLO                 fusionar tu pull request sin revisión")
    print("  Pull Shark           2 / 16 / 128 / 1024 pull requests fusionadas")
    print("  Pair Extraordinaire  1 / 10 / 24 / 48 con coautor de otra cuenta real")
    print("  Galaxy Brain         2 / 8 / 16 / 32 respuestas marcadas por otra persona")
    print("")
    print("Solo con personas reales, sin script")
    print("  Starstruck           16 / 128 / 512 / 4096 estrellas")
    print("  Public Sponsor       patrocinar a alguien en GitHub Sponsors")
    print("")
    print("Ya no se pueden conseguir")
    print("  Arctic Code Vault, Mars 2020 Contributor")
    print("  Heart On Your Sleeve y Open Sourcerer están inactivos")
    print("")
    print("Empieza con: python3 logros.py preparar && python3 logros.py rapidos")


def cmd_borrar(client, args):
    user, _scopes = me(client)
    if not args.si:
        raise SystemExit("Para borrar el repositorio de práctica: python3 logros.py borrar --si")
    repo = get_repo(client, user["login"])
    if repo is None:
        print("No existe {0}. No hay nada que borrar.".format(full_name(user["login"])))
        return
    try:
        client.get("/repos/{0}/contents/{1}".format(repo["full_name"], MARKER))
    except GitHubError as error:
        if error.status == 404:
            raise SystemExit("No borro {0} porque no tiene la marca de esta herramienta.".format(repo["full_name"]))
        raise
    if repo.get("stargazers_count"):
        raise SystemExit("No borro {0} porque tiene estrellas.".format(repo["full_name"]))
    if repo.get("forks_count"):
        raise SystemExit("No borro {0} porque tiene forks.".format(repo["full_name"]))
    if args.simular:
        print("Borraría https://github.com/{0}".format(repo["full_name"]))
        return
    client.delete("/repos/" + repo["full_name"])
    print("Repositorio borrado: {0}".format(repo["full_name"]))
    print("Revoca el token si ya no lo vas a usar.")


def add_volumen(parser, niveles):
    parser.add_argument("--cantidad", type=int, help="Cuántas pull requests nuevas crear")
    parser.add_argument("--hasta", type=int, help="Llegar a este total")
    parser.add_argument("--nivel", choices=sorted(niveles), help="base, bronce, plata u oro")
    parser.add_argument("--confirmar", action="store_true", help="Permite crear 33 o más de una vez")
    parser.add_argument("--simular", action="store_true", help="Muestra el plan sin escribir en GitHub")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Desbloquea logros del perfil de GitHub en un repositorio de tu cuenta."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("quien", help="Muestra la cuenta del token").set_defaults(func=cmd_quien)
    sub.add_parser("guia", help="Lista los logros y cuáles se pueden automatizar").set_defaults(func=cmd_guia)
    sub.add_parser("estado", help="Muestra el avance").set_defaults(func=cmd_estado)

    preparar = sub.add_parser("preparar", help="Crea el repositorio logros-github")
    preparar.add_argument("--privado", action="store_true", help="Créalo privado (Galaxy Brain lo pasará a público)")
    preparar.add_argument("--usar-este", action="store_true", help="Usa el repo aunque ya tenga otro contenido")
    preparar.set_defaults(func=cmd_preparar)

    quick = sub.add_parser("quickdraw", help="Abre y cierra un issue al momento")
    quick.add_argument("--simular", action="store_true")
    quick.set_defaults(func=cmd_quickdraw)

    shark = sub.add_parser("pull-shark", help="Fusiona las pull requests que falten")
    add_volumen(shark, NIVEL_PULL)
    shark.set_defaults(func=cmd_pull_shark)

    yolo = sub.add_parser("yolo", help="Fusiona una pull request tuya sin revisión")
    yolo.add_argument("--simular", action="store_true")
    yolo.add_argument("--confirmar", action="store_true")
    yolo.set_defaults(func=cmd_yolo)

    pair = sub.add_parser("pair", help="Fusiona pull requests con coautor")
    pair.add_argument("--con", help="Usuario real de GitHub de la otra persona")
    pair.add_argument("--coautor", help='Trailer manual: Nombre <correo>')
    add_volumen(pair, NIVEL_PAIR)
    pair.set_defaults(func=cmd_pair)

    rapidos = sub.add_parser("rapidos", help="Quickdraw, YOLO y Pull Shark base")
    rapidos.add_argument("--con", help="Si lo pasas, la primera pull request lleva coautor")
    rapidos.add_argument("--coautor", help='Trailer manual: Nombre <correo>')
    rapidos.add_argument("--simular", action="store_true")
    rapidos.set_defaults(func=cmd_rapidos)

    galaxy = sub.add_parser("galaxy", help="Prepara Galaxy Brain")
    galaxy.add_argument("--responder", action="store_true", help="Responde preguntas abiertas por otra persona")
    galaxy.add_argument("--simular", action="store_true")
    galaxy.set_defaults(func=cmd_galaxy)

    borrar = sub.add_parser("borrar", help="Borra solo el repositorio de práctica")
    borrar.add_argument("--si", action="store_true", help="Confirma el borrado")
    borrar.add_argument("--simular", action="store_true")
    borrar.set_defaults(func=cmd_borrar)
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.comando == "guia":
        args.func(None, args)
        return 0
    client = Client(get_token())
    try:
        args.func(client, args)
    except GitHubError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
