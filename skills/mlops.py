"""MLOps skill — model evaluation, DSPy optimization, benchmarking."""
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_eval",
            "description": "Evaluate a dataset against a metric (accuracy, BLEU, ROUGE, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "predictions_file": {"type": "string", "description": "JSON file with [{prediction, reference}]"},
                    "metric": {"type": "string", "default": "accuracy", "enum": ["accuracy", "bleu", "rouge", "f1", "exact_match"]},
                },
                "required": ["predictions_file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "model_benchmark",
            "description": "Benchmark an LLM with a set of test prompts and measure latency/quality.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompts": {"type": "string", "description": "JSON array of prompt strings"},
                    "provider": {"type": "string", "default": ""},
                    "model": {"type": "string", "default": ""},
                },
                "required": ["prompts"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "huggingface_model_info",
            "description": "Get info about a Hugging Face model.",
            "parameters": {
                "type": "object",
                "properties": {"model_id": {"type": "string", "description": "e.g. 'meta-llama/Llama-2-7b-chat-hf'"}},
                "required": ["model_id"],
            },
        },
    },
]


def run_eval(predictions_file: str, metric: str = "accuracy") -> str:
    try:
        from pathlib import Path
        data = json.loads(Path(predictions_file).read_text(encoding="utf-8"))
        preds = [d.get("prediction", "") for d in data]
        refs = [d.get("reference", "") for d in data]
        n = len(data)

        if metric == "accuracy" or metric == "exact_match":
            correct = sum(1 for p, r in zip(preds, refs) if str(p).strip() == str(r).strip())
            score = correct / n if n else 0
            return f"Metric: {metric}\nScore: {score:.4f} ({correct}/{n})"

        elif metric == "bleu":
            try:
                from nltk.translate.bleu_score import corpus_bleu
                import nltk
                nltk.download("punkt", quiet=True)
                refs_tok = [[r.split()] for r in refs]
                preds_tok = [p.split() for p in preds]
                score = corpus_bleu(refs_tok, preds_tok)
                return f"BLEU score: {score:.4f}"
            except ImportError:
                return "nltk not installed. Run: pip install nltk"

        elif metric in ("rouge", "f1"):
            try:
                from rouge_score import rouge_scorer
                scorer = rouge_scorer.RougeScorer(["rouge1", "rougeL"], use_stemmer=True)
                scores = [scorer.score(r, p) for p, r in zip(preds, refs)]
                avg_r1 = sum(s["rouge1"].fmeasure for s in scores) / n
                avg_rl = sum(s["rougeL"].fmeasure for s in scores) / n
                return f"ROUGE-1 F1: {avg_r1:.4f}\nROUGE-L F1: {avg_rl:.4f}"
            except ImportError:
                return "rouge-score not installed. Run: pip install rouge-score"

        return f"Unknown metric: {metric}"
    except Exception as e:
        return f"ERROR: {e}"


def model_benchmark(prompts: str, provider: str = "", model: str = "") -> str:
    try:
        import time
        prompt_list = json.loads(prompts) if isinstance(prompts, str) else prompts
        from agent.config import load_config
        from agent.providers.factory import get_provider
        cfg = load_config()
        if provider:
            cfg["provider"] = provider
        if model:
            cfg["model"] = model
        llm = get_provider(cfg)
        results = []
        for p in prompt_list[:5]:  # limit to 5
            t0 = time.time()
            resp = llm.chat([{"role": "user", "content": p}])
            elapsed = time.time() - t0
            content = (resp.get("content") or "")[:100]
            results.append(f"[{elapsed:.2f}s] {p[:50]}...\n  → {content}...")
        return f"Benchmark ({len(results)} prompts):\n" + "\n\n".join(results)
    except Exception as e:
        return f"ERROR: {e}"


def huggingface_model_info(model_id: str) -> str:
    try:
        import urllib.request, json
        url = f"https://huggingface.co/api/models/{model_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        downloads = data.get("downloads", 0)
        likes = data.get("likes", 0)
        pipeline = data.get("pipeline_tag", "")
        tags = ", ".join(data.get("tags", [])[:10])
        return (
            f"Model: {model_id}\n"
            f"Task: {pipeline}\n"
            f"Downloads: {downloads:,}  Likes: {likes:,}\n"
            f"Tags: {tags}\n"
            f"URL: https://huggingface.co/{model_id}"
        )
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {
    "run_eval": run_eval,
    "model_benchmark": model_benchmark,
    "huggingface_model_info": huggingface_model_info,
}
