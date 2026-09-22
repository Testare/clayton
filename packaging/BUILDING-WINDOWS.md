# Building Clayton on Windows

Step by step, from a clean Windows machine to `Clayton.exe`.

> This path has **not been tested** — it was written from PyInstaller's and pywebview's
> documented behaviour, with the platform-independent parts of the spec verified by a real
> build on Linux. If something here is wrong, the "If it goes wrong" section at the bottom
> covers the failures worth expecting first.

## 1. Prerequisites

**Python 3.11 or newer**, from [python.org](https://www.python.org/downloads/windows/) or the
Microsoft Store. During the installer, tick **"Add python.exe to PATH"** — without it the
commands below won't be found.

Check it:

```powershell
python --version
```

**WebView2 runtime.** This is what actually draws Clayton's interface. Windows 11 and recent
Windows 10 already have it; if in doubt, install the *Evergreen Standalone Installer* from
[Microsoft's WebView2 page](https://developer.microsoft.com/microsoft-edge/webview2/). It is
needed to **run** Clayton, not to build it — so a missing runtime shows up as a blank or
failed window rather than a build error.

**Git**, if you're cloning rather than downloading a zip.

## 2. Get the source

```powershell
git clone https://github.com/Testare/clayton.git
cd clayton
```

## 3. Set up an isolated environment

A virtual environment keeps these packages out of your system Python:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

Your prompt should now start with `(.venv)`. If PowerShell refuses with a script-execution
error, either use `cmd.exe` instead or allow it for this session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 4. Install what's needed

```powershell
pip install --upgrade pip
pip install pywebview pyinstaller
```

`pywebview` pulls in the .NET glue (`pythonnet`, `clr_loader`) that the WebView2 backend needs.

## 5. Try it before you build

Worth doing — it separates "the app doesn't work" from "the build doesn't work":

```powershell
python -m app.main
```

Clayton's window should open. Close it and carry on.

## 6. Build

Run this **from the repository root**, not from inside `packaging\`:

```powershell
pyinstaller packaging\clayton.spec
```

A few minutes later you'll have:

```
dist\Clayton\Clayton.exe
```

The whole `dist\Clayton` folder is the app — `Clayton.exe` needs the `_internal` folder beside
it. Move or zip the folder as a unit, not the `.exe` alone.

## 7. Check it

Double-click `Clayton.exe`. You should get:

- the Safari Ball icon on the executable and in the taskbar (**not** the Python icon)
- no console window behind the app
- the interface drawn normally

Your saved data lives in `%LOCALAPPDATA%\Clayton` and is **not** inside the build, so
rebuilding never touches your profiles, runs or charts.

## If it goes wrong

**`Unable to find '...qtwebengine_locales'`, or anything else mentioning Qt/PySide**
The spec excludes Qt on purpose, so this shouldn't happen — but if it does, it means a Qt
binding is installed in your venv and is being picked up anyway. `pip uninstall PySide6 PyQt5
PyQt6 qtpy` and rebuild.

**`System.ArgumentException: Argument 'picture' must be a picture that can be used as a Icon`**
A pywebview bug, not a problem with your build or the icon files. Its Windows backend sets the
window icon by extracting one from `sys.executable`, and `ExtractIconW` returns **1** — not 0 —
when that file has no icon to extract, which slips past pywebview's `!= 0` check and hands an
invalid handle to `System.Drawing.Icon`. It shows up when Python itself has no icon resource:
a Microsoft Store Python's app-execution alias is the usual culprit, and some venv shims too.

Clayton works around this (`_patch_windows_window_icon` in `app\main.py`), so **update to the
latest commit** if you hit it. If you're pinned to an older revision, installing Python from
python.org rather than the Store also avoids it.

**`RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from ...Python.Runtime.dll`**
The file is there — Windows refused to *load* it. Almost always **Mark of the Web**: anything
extracted from an internet-downloaded `.zip` is tagged untrusted, and .NET will not load a
managed assembly carrying that tag. The native part of pythonnet loads either way, which is
why the failure only appears at this late step.

From PowerShell, in the folder containing `Clayton.exe`:

```powershell
Get-ChildItem -Recurse | Unblock-File
```

Or right-click the `.zip` **before** extracting → Properties → tick **Unblock**. Builds you
compiled yourself are never affected — only downloaded ones.

If unblocking doesn't help, the remaining candidates are a missing **.NET Framework 4.x**, or
a 32/64-bit mismatch between the build and your .NET. Clayton shows this guidance in a dialog
rather than a bare traceback.

**The window opens blank, or the app exits immediately**
Almost always the WebView2 runtime (step 1). Install the Evergreen redistributable and retry.

**`ModuleNotFoundError` for something at runtime that worked under `python -m app.main`**
PyInstaller missed an import it couldn't see statically. Add the module's name to
`hiddenimports` in `packaging\clayton.spec` and rebuild.

**The exe shows the Python icon, or groups oddly in the taskbar**
Windows caches icons aggressively. Try a different folder or `ie4uinit.exe -show`. If it
persists, that's a real bug — `app\main.py`'s `_set_app_identity` is what sets it.

**The build succeeds but the exe won't start, with no message**
Rebuild with a console attached to see the traceback: edit `packaging\clayton.spec`, set
`console=True` in the `EXE(...)` block, rebuild, and run it from a terminal. Set it back
afterwards.

## Making a single .exe (optional)

The default build is a folder, which starts faster. For one self-contained file, change the
`EXE(...)` call in the spec to include `a.binaries, a.datas` and drop the `COLLECT(...)`
block — see PyInstaller's
[one-file mode](https://pyinstaller.org/en/stable/usage.html#bundling-to-one-file). Expect a
noticeably slower launch, since it unpacks itself on every run.
