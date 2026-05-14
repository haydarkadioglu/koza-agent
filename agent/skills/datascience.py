"""Data science skill — Jupyter cells, pandas queries, matplotlib plots."""
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_jupyter_cell",
            "description": "Execute Python code in a persistent Jupyter kernel and return output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "kernel_id": {"type": "string", "default": "default", "description": "Named kernel session"},
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pandas_query",
            "description": "Load a CSV/Excel file and run a pandas query/operation on it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "query": {"type": "string", "description": "Pandas expression, e.g. 'df[df.age > 30].head()'"},
                },
                "required": ["file_path", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "matplotlib_plot",
            "description": "Run matplotlib code and save the plot as a PNG file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Matplotlib code (use plt.savefig or auto-saved)"},
                    "output_path": {"type": "string", "default": "plot.png"},
                },
                "required": ["code"],
            },
        },
    },
]

# Per-session kernel state (variable namespace)
_kernels: dict = {}


def run_jupyter_cell(code: str, kernel_id: str = "default") -> str:
    import io, sys, traceback
    if kernel_id not in _kernels:
        _kernels[kernel_id] = {}
    ns = _kernels[kernel_id]
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        exec(compile(code, "<cell>", "exec"), ns)
        out = sys.stdout.getvalue()
        err = sys.stderr.getvalue()
    except Exception:
        out = ""
        err = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
    result = []
    if out.strip():
        result.append(out.strip())
    if err.strip():
        result.append(f"STDERR:\n{err.strip()}")
    return "\n".join(result) or "(no output)"


def pandas_query(file_path: str, query: str) -> str:
    try:
        import pandas as pd
        if file_path.endswith(".xlsx") or file_path.endswith(".xls"):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
        result = eval(query, {"df": df, "pd": pd})
        return str(result)
    except ImportError:
        return "pandas not installed. Run: pip install pandas openpyxl"
    except Exception as e:
        return f"ERROR: {e}"


def matplotlib_plot(code: str, output_path: str = "plot.png") -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ns = {"plt": plt}
        exec(code, ns)
        plt.savefig(output_path, bbox_inches="tight")
        plt.close("all")
        return f"Plot saved to: {output_path}"
    except ImportError:
        return "matplotlib not installed. Run: pip install matplotlib"
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "run_jupyter_cell": run_jupyter_cell,
    "pandas_query": pandas_query,
    "matplotlib_plot": matplotlib_plot,
}
