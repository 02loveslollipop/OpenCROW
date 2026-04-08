"""Flask UI for OpenCROW Constellation."""

from __future__ import annotations

import argparse
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, flash, redirect, render_template, request, session, stream_with_context, url_for

from .client import ConstellationAPIClient, ConstellationAPIError
from .config import ClientSettings, UISettings, load_ui_settings


TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
STATIC_ROOT = Path(__file__).resolve().parent / "static"


def _client_settings(ui_settings: UISettings, token: str) -> ClientSettings:
    return ClientSettings(
        api_base_url=ui_settings.backend_api_base_url,
        ws_base_url=ui_settings.backend_ws_base_url,
        token=token,
        private_prompt=None,
        private_prompt_file=None,
        state_dir_name=".opencrow-constellation",
        request_timeout_sec=20,
        prompt_output_name="generated-prompt.md",
    )


def create_app(ui_settings: UISettings | None = None) -> Flask:
    resolved_ui_settings = ui_settings or load_ui_settings()
    app = Flask(__name__, template_folder=str(TEMPLATE_ROOT), static_folder=str(STATIC_ROOT))
    app.secret_key = resolved_ui_settings.secret_key
    app.config["ui_settings"] = resolved_ui_settings

    def _backend_client_headers() -> dict[str, str]:
        if not resolved_ui_settings.shared_secret:
            return {}
        return {"X-Constellation-UI-Auth": resolved_ui_settings.shared_secret}

    def backend_client() -> ConstellationAPIClient:
        token = str(session.get("token", "")).strip()
        return ConstellationAPIClient(
            _client_settings(resolved_ui_settings, token),
            extra_headers=_backend_client_headers(),
        )

    def require_login(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("token"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def ensure_ui_member(topic: str) -> dict[str, Any]:
        session_members = session.get("ui_members")
        if not isinstance(session_members, dict):
            session_members = {}
        existing = session_members.get(topic)
        if isinstance(existing, dict) and existing.get("id"):
            return existing
        client = backend_client()
        joined = client.join_topic(
            topic,
            display_name=str(session.get("display_name") or resolved_ui_settings.default_display_name),
            client_kind="ui",
            metadata={"via": "flask-ui"},
        )
        session_members[topic] = joined.member
        session["ui_members"] = session_members
        session.modified = True
        return joined.member

    @app.context_processor
    def inject_common() -> dict[str, Any]:
        return {
            "ui_settings": resolved_ui_settings,
            "display_name": session.get("display_name"),
        }

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if request.method == "POST":
            token = request.form.get("token", "").strip()
            display_name = request.form.get("display_name", "").strip() or resolved_ui_settings.default_display_name
            client = ConstellationAPIClient(_client_settings(resolved_ui_settings, token))
            try:
                client.validate_auth()
            except ConstellationAPIError as exc:
                flash(str(exc), "error")
            else:
                session.clear()
                session["token"] = token
                session["display_name"] = display_name
                flash("Authenticated against the Constellation backend.", "success")
                return redirect(url_for("index"))
        return render_template("login.html")

    @app.post("/logout")
    def logout() -> Any:
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @require_login
    def index() -> Any:
        client = backend_client()
        payload = client.list_topics()
        return render_template("index.html", topics=payload.get("topics", []))

    @app.post("/topics")
    @require_login
    def create_topic() -> Any:
        client = backend_client()
        handoff_urls = ConstellationAPIClient.format_handoff_urls(request.form.get("handoff_urls", ""))
        try:
            payload = client.create_topic(
                title=request.form.get("title", "").strip(),
                description=request.form.get("description", "").strip(),
                category=request.form.get("category", "").strip() or "misc",
                handoff_urls=handoff_urls,
                slug=request.form.get("slug", "").strip() or None,
            )
        except ConstellationAPIError as exc:
            flash(str(exc), "error")
            return redirect(url_for("index"))
        flash(f"Topic created. Single-use password: {payload['single_use_password']}", "success")
        return redirect(url_for("topic_detail", topic=payload["topic"]["slug"]))

    @app.route("/topics/<topic>")
    @require_login
    def topic_detail(topic: str) -> Any:
        client = backend_client()
        topic_payload = client.get_topic(topic)["topic"]
        history = client.history(topic, limit=150).get("history", [])
        documents = client.list_docs(topic).get("documents", [])
        artifacts = client.list_final_artifacts(topic).get("artifacts", [])
        ui_member = ensure_ui_member(topic)
        ws_url = client.build_ws_url(
            topic=topic,
            member_id=ui_member["id"],
            client_kind="ui",
            display_name=str(session.get("display_name") or resolved_ui_settings.default_display_name),
        )
        ws_protocols = client.build_ws_subprotocols()
        return render_template(
            "topic.html",
            topic=topic_payload,
            history=history,
            documents=documents,
            artifacts=artifacts,
            ui_member=ui_member,
            ws_url=ws_url,
            ws_protocols=ws_protocols,
        )

    @app.post("/topics/<topic>/update")
    @require_login
    def update_topic(topic: str) -> Any:
        client = backend_client()
        handoff_urls = ConstellationAPIClient.format_handoff_urls(request.form.get("handoff_urls", ""))
        try:
            client.update_topic(
                topic,
                title=request.form.get("title", "").strip(),
                description=request.form.get("description", "").strip(),
                category=request.form.get("category", "").strip() or "misc",
                handoff_urls=handoff_urls,
            )
            flash("Topic updated.", "success")
        except ConstellationAPIError as exc:
            flash(str(exc), "error")
        return redirect(url_for("topic_detail", topic=topic))

    @app.post("/topics/<topic>/send")
    @require_login
    def send_message(topic: str) -> Any:
        client = backend_client()
        ui_member = ensure_ui_member(topic)
        message_type = request.form.get("message_type", "chat_message").strip() or "chat_message"
        body = request.form.get("body", "").strip()
        if not body:
            flash("Message body is required.", "error")
            return redirect(url_for("topic_detail", topic=topic))
        try:
            client.send_message(
                topic,
                member_id=ui_member["id"],
                message_type=message_type,
                body=body,
            )
            flash(f"Sent {message_type}.", "success")
        except ConstellationAPIError as exc:
            flash(str(exc), "error")
        return redirect(url_for("topic_detail", topic=topic))

    @app.post("/topics/<topic>/admin/regenerate")
    @require_login
    def regenerate_admin(topic: str) -> Any:
        client = backend_client()
        try:
            payload = client.regenerate_admin_secret(topic)
            flash(f"New single-use password: {payload['single_use_password']}", "success")
        except ConstellationAPIError as exc:
            flash(str(exc), "error")
        return redirect(url_for("topic_detail", topic=topic))

    @app.post("/topics/<topic>/delete")
    @require_login
    def delete_topic(topic: str) -> Any:
        client = backend_client()
        try:
            client.delete_topic(topic)
            flash(f"Deleted topic `{topic}`.", "success")
        except ConstellationAPIError as exc:
            flash(str(exc), "error")
            return redirect(url_for("topic_detail", topic=topic))
        session_members = session.get("ui_members")
        if isinstance(session_members, dict) and topic in session_members:
            session_members.pop(topic, None)
            session["ui_members"] = session_members
        return redirect(url_for("index"))

    @app.get("/files/<file_id>")
    @require_login
    def download_file(file_id: str) -> Response:
        client = backend_client()
        response = client._request("GET", f"/files/{file_id}", stream=True)
        headers = {}
        for name in ("Content-Type", "Content-Disposition"):
            value = response.headers.get(name)
            if value:
                headers[name] = value

        def generate() -> Any:
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                response.close()

        return Response(stream_with_context(generate()), headers=headers, direct_passthrough=True)

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Bind host override.")
    parser.add_argument("--port", type=int, help="Bind port override.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_ui_settings()
    if args.host:
        settings = UISettings(
            backend_api_base_url=settings.backend_api_base_url,
            backend_ws_base_url=settings.backend_ws_base_url,
            listen_host=args.host,
            listen_port=args.port or settings.listen_port,
            secret_key=settings.secret_key,
            default_display_name=settings.default_display_name,
            shared_secret=settings.shared_secret,
        )
    elif args.port:
        settings = UISettings(
            backend_api_base_url=settings.backend_api_base_url,
            backend_ws_base_url=settings.backend_ws_base_url,
            listen_host=settings.listen_host,
            listen_port=args.port,
            secret_key=settings.secret_key,
            default_display_name=settings.default_display_name,
            shared_secret=settings.shared_secret,
        )
    app = create_app(settings)
    app.run(host=settings.listen_host, port=settings.listen_port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
