"""Command line interface: run / preview / force / install / uninstall / status."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import __version__, state
from .config import ConfigError, load_config
from .format import render_markdown

log = logging.getLogger("mainichi_news")


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"日付は YYYY-MM-DD: {value}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mainichi-news",
        description="島根県のローカルニュースを毎朝メールで届ける",
    )
    parser.add_argument("--version", action="version", version=f"mainichi-news {__version__}")
    parser.add_argument("--config", type=Path, help="config.toml のパス")
    parser.add_argument("--env", type=Path, help=".env のパス")
    parser.add_argument("-v", "--verbose", action="store_true", help="デバッグログ")
    parser.add_argument("-q", "--quiet", action="store_true", help="警告以上のみ")

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="今日の分を実行（同日2回目は何もしない）")
    run.add_argument("--force", action="store_true", help="同日でも再実行する")

    force = sub.add_parser("force", help="冪等ガードを無視して実行（run --force と同じ）")
    force.add_argument("--no-email", action="store_true", help="メールを送らない")

    preview = sub.add_parser("preview", help="メール送らず Markdown を標準出力")
    preview.add_argument("--date", type=parse_day, help="対象日 (既定: 今日)")

    sub.add_parser("status", help="設定と最終実行を表示")

    install = sub.add_parser("install", help="systemd / launchd / Task Scheduler に登録")
    install.add_argument("--no-enable", action="store_true", help="ファイル配置のみ")
    install.add_argument("--print", dest="print_only", action="store_true", help="書き込まず内容を表示")
    install.add_argument(
        "--platform", choices=["linux", "macos", "windows"], help="対象OS（既定: 自動判定）"
    )

    uninstall = sub.add_parser("uninstall", help="登録を解除")
    uninstall.add_argument(
        "--platform", choices=["linux", "macos", "windows"], help="対象OS（既定: 自動判定）"
    )
    return parser


def setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def cmd_status(cfg) -> int:
    print(f"mainichi-news {__version__}")
    print(f"config   : {cfg.config_path} {'(あり)' if cfg.config_path.is_file() else '(なし=既定値)'}")
    print(f"env      : {cfg.env_path} {'(あり)' if cfg.env_path.is_file() else '(なし)'}")
    print(f"queries  : {', '.join(cfg.source.queries)}")
    print(f"model    : {cfg.summarize.model} ({cfg.summarize.base_url})")
    print(f"api key  : {'設定済み' if cfg.api_key else '未設定 → 要約なしモード'}")
    print(
        "email    : "
        + (f"{cfg.deliver.to} via {cfg.deliver.smtp_host}:{cfg.deliver.smtp_port}"
           if cfg.deliver.email_enabled
           else "未設定 → 保存のみ")
    )
    print(f"digest   : {cfg.digest_dir}")
    last = state.last_run()
    info = state.last_run_info()
    print(f"last-run : {last.isoformat() if last else '(なし)'} ({state.last_run_path()})")
    if info:
        print(f"           articles={info.get('articles', '?')} delivered={info.get('delivered', '?')}")
    today_done = last == date.today()
    print(f"today    : {'配信済み（run は no-op）' if today_done else '未配信'}")
    for warning in cfg.warnings:
        print(f"warning  : {warning}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose, args.quiet)

    try:
        cfg = load_config(args.config, args.env)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    for warning in cfg.warnings:
        log.debug("config: %s", warning)

    if args.command == "status":
        return cmd_status(cfg)

    if args.command == "preview":
        from .pipeline import build_digest

        day = args.date or date.today()
        digest = build_digest(cfg, day)
        if not digest.all_stories:
            log.error("記事が取得できなかった")
            return 1
        print(render_markdown(digest))
        return 0

    if args.command == "install":
        if args.print_only:
            from .install import artifacts

            for artifact in artifacts(args.platform):
                print(f"# ==== {artifact.kind}: {artifact.path} ====")
                print(artifact.content)
            return 0

        from .install import InstallError, install

        try:
            paths = install(enable=not args.no_enable, platform=args.platform)
        except InstallError as exc:
            log.error("%s", exc)
            return 1
        for path in paths:
            print(f"installed: {path}")
        return 0

    if args.command == "uninstall":
        from .install import InstallError, uninstall

        try:
            removed = uninstall(platform=args.platform)
        except InstallError as exc:
            log.error("%s", exc)
            return 1
        if not removed:
            print("登録は見つからなかった")
        for path in removed:
            print(f"removed: {path}")
        return 0

    from .pipeline import run_once

    if args.command == "run":
        return run_once(cfg, force=args.force)
    if args.command == "force":
        return run_once(cfg, force=True, email=not args.no_email)
    parser.error(f"unknown command: {args.command}")
    return 2
