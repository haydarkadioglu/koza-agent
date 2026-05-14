"""Creative skill — architecture diagrams, ASCII art, image generation."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "ascii_art",
            "description": "Convert text to ASCII art using pyfiglet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "font": {"type": "string", "default": "slant", "description": "Figlet font name"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "architecture_diagram",
            "description": "Generate a Mermaid.js diagram definition for architecture/flowcharts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Natural language description of the architecture"},
                    "diagram_type": {
                        "type": "string",
                        "enum": ["flowchart", "sequenceDiagram", "classDiagram", "erDiagram", "gantt"],
                        "default": "flowchart",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image using OpenAI DALL-E and save to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "output_path": {"type": "string", "default": "generated_image.png"},
                    "size": {"type": "string", "default": "1024x1024", "enum": ["256x256", "512x512", "1024x1024"]},
                },
                "required": ["prompt"],
            },
        },
    },
]


def ascii_art(text: str, font: str = "slant") -> str:
    try:
        import pyfiglet
        return pyfiglet.figlet_format(text, font=font)
    except ImportError:
        return f"pyfiglet not installed. Run: pip install pyfiglet\nFallback:\n{'='*40}\n  {text.upper()}\n{'='*40}"
    except Exception as e:
        return f"ERROR: {e}"


def architecture_diagram(description: str, diagram_type: str = "flowchart") -> str:
    """Returns a Mermaid diagram skeleton based on description."""
    template = {
        "flowchart": f"```mermaid\nflowchart TD\n    %% {description}\n    A[Start] --> B[Process]\n    B --> C[End]\n```",
        "sequenceDiagram": f"```mermaid\nsequenceDiagram\n    %% {description}\n    participant A\n    participant B\n    A->>B: Request\n    B-->>A: Response\n```",
        "classDiagram": f"```mermaid\nclassDiagram\n    %% {description}\n    class MyClass {{\n        +attribute: Type\n        +method()\n    }}\n```",
        "erDiagram": f"```mermaid\nerDiagram\n    %% {description}\n    ENTITY1 ||--o{{ ENTITY2 : has\n```",
        "gantt": f"```mermaid\ngantt\n    title {description}\n    dateFormat YYYY-MM-DD\n    section Phase 1\n    Task1 :a1, 2024-01-01, 7d\n```",
    }
    return template.get(diagram_type, template["flowchart"])


def generate_image(prompt: str, output_path: str = "generated_image.png", size: str = "1024x1024") -> str:
    try:
        from openai import OpenAI
        import urllib.request
        client = OpenAI()
        response = client.images.generate(prompt=prompt, n=1, size=size)
        url = response.data[0].url
        urllib.request.urlretrieve(url, output_path)
        return f"Image saved to: {output_path}\nURL: {url}"
    except ImportError:
        return "openai package not installed."
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"ascii_art": ascii_art, "architecture_diagram": architecture_diagram, "generate_image": generate_image}
