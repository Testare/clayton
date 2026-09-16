"""Clayton desktop application package.

Thin shell around ``claytonlib``: a JSON ``Store`` (``store.py``), the app entity
model (``models.py``), and — added as areas land — a Python facade and a pywebview
front end. Nothing here reaches into the notebook data layout; persistence goes
through the Store so the same code runs under the desktop build (local files) and,
later, other backends.
"""
