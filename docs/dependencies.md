# Dependencies

Every check runs in a Docker container with no network. A project whose tests need `pytest` or any
other third-party package therefore needs an image that already contains them.
`tribunal build-image` builds one. Network access is used for that build only.

## Build an image

```
tribunal build-image --repo-path /path/to/repo --ref main
```

It prints the image tag and a `TRIBUNAL_SANDBOX_IMAGE=...` line. Use the tag with
`tribunal submit --image TAG`, or let `submit` do both steps:

```
tribunal submit --repo-path /path/to/repo --base main --head HEAD --build-env \
  --test-cmd "python -m pytest -q"
```

Use `python -m pytest`, not `pytest`. The image sets `PYTHONPATH=/work:/work/src`, so the project
imports from a flat or a `src/` layout. The project itself is not installed.

## What gets installed

| Source | Used |
| --- | --- |
| `requirements.txt`, `requirements-dev.txt`, `requirements-test.txt`, `dev-requirements.txt`, `test-requirements.txt`, `requirements/dev.txt`, `requirements/test.txt` | Every one that exists, following `-r` includes inside the repository |
| `pyproject.toml` `dependencies` | Always |
| `pyproject.toml` extras and dependency groups | Those named `dev`, `test` or `tests`, unless `--extra` or `--group` is given |

`--requirements FILE` replaces the file detection. All of these options can be repeated.

Lines that are not plain requirement specifiers are skipped and listed in the output: URLs, VCS
references, local paths, editable installs, `name @ url` references, pip options such as
`--index-url`, and constraint files. The project's own name is skipped too, because a PyPI package
with the same name would otherwise be installed in its place.

## Trust model

The build runs package code with network access on your machine, so it is restricted:

- Dependencies come from the base commit, never from the change under review. A pull request
  cannot change what is installed. A new dependency in a pull request shows up as an import failure
  in that pull request's run.
- The build context contains one generated `requirements.txt` and a Dockerfile. No repository code
  is copied into it.
- Only wheels are installed by default (`pip --only-binary=:all:`). Wheels do not run build scripts.
  `--allow-sdist` permits source builds, which do.
- Analysis runs offline in the built image, with the same restrictions as before.

## Caching and reproducibility

The tag is `tribunal-env:` plus a hash of the base image, the requirements and `--allow-sdist`. The
same inputs give the same tag, and an existing image is reused. `--force` rebuilds it.

Unpinned requirements resolve to whatever is newest at build time. The command warns about them,
and the same tag can then hold different packages on different days. Pin dependencies with `==` for
reproducible images.

## GitHub Action

Set `build-env: true`. `sandbox-image` becomes the base image, and `allow-sdist` is available. The
Action builds from the pull request's merge base.

## Replay

A receipt records the image tag it ran in. `tribunal replay` needs that image on the machine. If it
is gone, `tribunal build-image --ref BASE_SHA` with the same options recreates the same tag.

## Limits

- Python only, with pip.
- Dependencies that need system libraries missing from the base image fail to build. Pick a base
  image that has them, or one built for your project, with `--base-image`.
- Private package indexes are not supported, since pip options are skipped.
- The build uses your machine's network and Docker. Nothing else on the host is exposed to it.
