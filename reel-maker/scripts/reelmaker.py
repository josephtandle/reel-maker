#!/usr/bin/env python3
"""Reel Maker v2: local, editable, word-timed vertical reels."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
sys.dont_write_bytecode = True
from rm_env import (NeedsInput, log, home, venv_python, reexec, available, apple_silicon,
                    ffmpeg, ffprobe, system_ffmpeg, encoder, run, long_run, read_json,
                    write_json, source_job)

MEDIA = {".mp4",".mov",".mkv",".webm",".avi",".m4v",".mp3",".wav",".m4a",".aac",".flac",".ogg"}


def installation_plan(backend="auto", model="small", no_faces=False):
    backend = ("mlx" if apple_silicon() else "faster") if backend == "auto" else backend
    packages = ["Pillow>=10.1","numpy"]
    sizes = ["Pillow ~5 MB","numpy ~20 MB"]
    if not no_faces:
        packages.append("opencv-python-headless<5")
        sizes.append("opencv-python-headless ~40 MB (face-aware crop)")
    if backend != "none":
        packages.append("mlx-whisper" if backend == "mlx" else "faster-whisper")
        sizes.append("mlx-whisper ~30 MB" if backend == "mlx" else "faster-whisper ~80 MB")
    if not system_ffmpeg():
        packages.append("imageio-ffmpeg")
        sizes.append("imageio-ffmpeg ~70 MB (no system ffmpeg)")
    model_size = {"small":"~480 MB","medium":"~1.5 GB","large-v3-turbo":"~1.6 GB"}[model]
    return {"venv":str(home()/"venv"),"packages":packages,"download_estimates":sizes,
            "backend":backend,"model":None if backend=="none" else model,
            "model_download":None if backend=="none" else model_size}


def doctor(as_json=False):
    from rm_transcribe import choose_backend
    system = platform.system()
    system = "macOS" if system=="Darwin" else "WSL" if "microsoft" in platform.release().lower() else system
    result = {"os":system,"arch":platform.machine(),"apple_silicon":apple_silicon(),
              "python":platform.python_version(),"venv_exists":venv_python().exists(),
              "python_executable":sys.executable,"venv_active":Path(sys.prefix).resolve()==(home()/"venv").resolve(),
              "dependencies":{name:available(module) for name,module in (("Pillow","PIL"),("numpy","numpy"),("cv2","cv2"),
                  ("mlx_whisper","mlx_whisper"),("faster_whisper","faster_whisper"),("whisper","whisper"))},
              "backend_chosen":choose_backend(),"brand_present":(home()/"brand.json").is_file()}
    try:
        path = ffmpeg()
        result["ffmpeg"] = {"path":path,"version":run([path,"-version"]).stdout.splitlines()[0],
                            "encoder":encoder(),"has_libx264":encoder()=="libx264"}
        result["ffprobe"] = ffprobe() or "ffmpeg metadata fallback"
    except (NeedsInput,OSError,RuntimeError) as exc:
        result["ffmpeg"] = {"error":str(exc)}
        result["ffprobe"] = ffprobe() or "ffmpeg metadata fallback"
    for name in ("node","npx"):
        path = shutil.which(name)
        try:
            result[name] = run([path,"--version"]).stdout.strip() if path else None
        except (OSError,RuntimeError):
            result[name] = None
    result["next_steps"] = []
    from rm_crop import face_classifiers
    try:
        face_classifiers()
        result["face_detection"] = {"available": True}
    except Exception:
        result["face_detection"] = {"available": False, "fix": "re-run setup --yes"}
        result["next_steps"].append("Face detection unavailable; re-run setup --yes.")
    if not result["dependencies"]["Pillow"] or "error" in result["ffmpeg"]:
        result["next_steps"].append("Run setup to review the local installation plan; setup --yes approves downloads.")
    if not result["backend_chosen"]:
        result["next_steps"].append("Install a transcription backend with setup --yes, or supply --transcript FILE.")
    result["next_steps"].append("Run brand to configure your look, then make INPUT --stop-after find to review moments.")
    result["setup_plan"] = installation_plan()
    result["optional_downloads"] = ["Pillow ~5 MB","numpy ~20 MB","opencv-python-headless ~40 MB",
                                  "mlx-whisper ~30 MB + model (small ~480 MB; large-v3-turbo ~1.6 GB)",
                                  "faster-whisper ~80 MB + model (small ~480 MB)",
                                  "imageio-ffmpeg ~70 MB (only if no ffmpeg)"]
    if as_json:
        print(json.dumps(result,ensure_ascii=False))
    else:
        log("Environment check")
        for key in ("os","arch","apple_silicon","python","venv_exists","ffmpeg","ffprobe","dependencies","face_detection","backend_chosen","node","npx","brand_present"):
            print(f"{key}: {result[key]}")
        print("\nNext step:")
        for step in result["next_steps"]:
            print("- " + step)
        print("\nSETUP PLAN\n" + json.dumps(result["setup_plan"],indent=2))
        for estimate in result["optional_downloads"]:
            print("- " + estimate)
    return 0


def setup(args):
    plan = installation_plan(args.backend,args.model,args.no_faces)
    log("SETUP PLAN")
    print(json.dumps(plan,indent=2))
    if sys.version_info < (3,9):
        raise NeedsInput("Python 3.9 or newer is required. Install a supported Python and rerun setup.")
    if not args.yes:
        log("NEEDS_CONSENT: rerun setup --yes to install this plan. No changes made.")
        return 3
    home().mkdir(parents=True,exist_ok=True)
    if not venv_python().exists():
        long_run([sys.executable,"-m","venv",home()/"venv"],"Creating local virtual environment")
    py = venv_python()
    long_run([py,"-m","pip","install","--quiet","--upgrade","pip"],"Updating local pip")
    long_run([py,"-m","pip","install",*plan["packages"]],"Installing local tools")
    if plan["backend"] == "mlx":
        from rm_transcribe import mlx_repo
        code = ("from huggingface_hub import snapshot_download; snapshot_download("
                + repr(mlx_repo(args.model)) + ", cache_dir=" + repr(str(home()/"models"/"mlx")) + ")")
        long_run([py,"-c",code],"Downloading transcription model")
    elif plan["backend"] == "faster":
        code = ("from faster_whisper import WhisperModel; WhisperModel("
                + repr(args.model) + ", compute_type='int8', download_root=" + repr(str(home()/"models"/"faster")) + ")")
        long_run([py,"-c",code],"Downloading transcription model")
    write_json(home()/"settings.json",{"backend":plan["backend"],"model":args.model})
    log("Setup complete. Run doctor, then make INPUT.")
    return 0


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command",required=True)
    p = sub.add_parser("doctor",help="Check tools without installing anything")
    p.add_argument("--json",action="store_true")
    p = sub.add_parser("setup",help="Review or approve local tools and model downloads")
    p.add_argument("--yes",action="store_true")
    p.add_argument("--backend",choices=["auto","mlx","faster","none"],default="auto")
    p.add_argument("--model",choices=["small","medium","large-v3-turbo"],default="small")
    p.add_argument("--no-faces",action="store_true")
    p = sub.add_parser("brand",help="Configure local branding")
    for flag in ("name","handle","color","accent","logo","cta-word","cta-text","font"):
        p.add_argument("--"+flag)
    p.add_argument("--show",action="store_true")
    p.add_argument("--reset",action="store_true")
    p = sub.add_parser("transcribe",help="Transcribe offline or import timed text")
    p.add_argument("input",type=Path)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--backend",choices=["auto","mlx","faster","whisper"],default="auto")
    p.add_argument("--model")
    p.add_argument("--transcript",type=Path)
    p.add_argument("--language")
    p.add_argument("--force",action="store_true")
    p = sub.add_parser("find",help="Suggest complete, non-overlapping moments")
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--count",type=int)
    p.add_argument("--min",dest="minimum",type=float,default=20)
    p.add_argument("--max",dest="maximum",type=float,default=60)
    p.add_argument("--force",action="store_true")
    for command in ("render","verify"):
        p = sub.add_parser(command)
        p.add_argument("--out",type=Path,required=True)
        if command == "render":
            p.add_argument("--only", help="Comma-separated reel numbers 1..N as shown in report.md")
            render_flags(p)
            p.add_argument("--no-logo",action="store_true")
            p.add_argument("--keep-temp",action="store_true")
    p = sub.add_parser("make",help="Transcribe, find, render and verify")
    p.add_argument("input",type=Path)
    p.add_argument("--out",type=Path)
    p.add_argument("--count",type=int)
    render_flags(p)
    p.add_argument("--transcript",type=Path)
    p.add_argument("--backend",choices=["auto","mlx","faster","whisper"],default="auto")
    p.add_argument("--model")
    p.add_argument("--stop-after",choices=["transcribe","find"])
    p.add_argument("--auto",action="store_true",help="Run unattended through rendering")
    return root


def render_flags(p):
    p.add_argument("--layout",choices=["auto","fill","fit"],default="auto")
    p.add_argument("--style",choices=["clean","bold"],default="bold")


def summary(job, status, files=None, **extra):
    print("RESULT " + json.dumps({"job":str(Path(job).resolve()),"files":files or [],"status":status,**extra},ensure_ascii=False))


def execute(args):
    if args.command == "doctor":
        return doctor(args.json)
    log(args.command.capitalize())
    if args.command == "setup":
        return setup(args)
    if args.command == "brand":
        from rm_brand import configure
        configure(args)
        return 0
    if args.command == "transcribe":
        from rm_transcribe import transcribe
        transcribe(args.input,args.out,args.backend,args.model,args.transcript,args.language,args.force)
        return 0
    if args.command == "find":
        from rm_moments import find
        find(args.out,args.count,args.minimum,args.maximum,args.force)
        return 0
    if args.command in ("render","verify"):
        if not available("PIL"):
            raise NeedsInput("Pillow is missing. Run setup --yes --backend none or install requirements.txt.")
        if args.command == "render":
            from rm_render import render
            report = render(args.out,[value.strip() for value in args.only.split(",")] if args.only is not None else None,args.layout,args.style,args.no_logo,args.keep_temp)
            summary(args.out,report["status"],report["files"])
        else:
            from rm_verify import verify
            report = verify(args.out)
        return 4 if report["status"]=="FAIL" else 0
    from rm_transcribe import transcribe
    from rm_moments import find
    sources = sorted((p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() in MEDIA),key=lambda p:p.name.lower()) if args.input.is_dir() else [args.input]
    if not sources:
        raise NeedsInput("No supported media files found in the input folder.")
    exit_code, results = 0, []
    for source in sources:
        duplicate_stem = sum(p.stem.casefold()==source.stem.casefold() for p in sources)>1
        child = source.stem + (" - " + source.suffix.lstrip(".") if duplicate_stem else "")
        target = args.out/child if args.out and args.input.is_dir() else args.out
        job = target or source.parent
        try:
            job = source_job(source,target)
            transcribe(source,job,backend=args.backend,model=args.model,transcript=args.transcript)
            status, files = "TRANSCRIBED", ["working/transcript.json"]
            if args.stop_after != "transcribe":
                find(job,args.count)
                status,files = "PREPARED",["moments.json"]
                if args.stop_after != "find":
                    if not available("PIL"):
                        raise NeedsInput("Pillow is missing. Run setup --yes --backend none.")
                    from rm_render import render
                    report = render(job,layout=args.layout,style=args.style)
                    status,files = report["status"],report["files"]
                    if status == "FAIL":
                        exit_code = 4
        except (NeedsInput,FileNotFoundError) as exc:
            log("NEEDS_INPUT: " + source.name + ": " + str(exc))
            exit_code = max(exit_code,2)
            status,files = "NEEDS_INPUT",[]
        except Exception as exc:
            log("FAILED: " + source.name + ": " + str(exc))
            exit_code = max(exit_code,1)
            status,files = "FAILED",[]
        results.append({"job":str(job),"status":status,"files":files})
        summary(job,status,files)
    if len(results)>1:
        summary(args.out or sources[0].parent,"FAIL" if exit_code else "PASS",jobs=results)
    return exit_code


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return execute(args)
    except (NeedsInput,FileNotFoundError) as exc:
        log("NEEDS_INPUT: " + str(exc))
        code,status = 2,"NEEDS_INPUT"
    except KeyboardInterrupt:
        log("Interrupted; resume using the same job folder.")
        code,status = 1,"INTERRUPTED"
    except Exception as exc:
        log("FAILED: " + str(exc))
        code,status = 1,"FAILED"
    if args.command in ("make","render"):
        summary(getattr(args,"out",None) or Path.cwd(),status)
    return code


if __name__ == "__main__":
    reexec()
    raise SystemExit(main())
