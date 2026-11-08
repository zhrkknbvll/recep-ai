import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATA_FILE = BASE_DIR / "data.txt"

GEMINI_API_KEY = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
)

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
)


class RecipeAIError(Exception):
    pass


def normalize(value) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").lower().strip()
    )


def parse_products(value) -> list[str]:
    if not value:
        return []

    if isinstance(value, str):
        values = re.split(r"[,;\n]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = [str(value)]

    return [
        normalize(item)
        for item in values
        if normalize(item)
    ]


def parse_time_limit(value) -> Optional[int]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = normalize(value)

    if text in ("любое", "любой", "без ограничений", "any"):
        return None

    match = re.search(r"\d+", text)

    if not match:
        return None

    number = int(match.group())

    if "час" in text:
        return number * 60

    return number


def extract_value(block, field):
    match = re.search(
        rf"(?im)^\s*{re.escape(field)}\s*:\s*(.*?)\s*$",
        block
    )

    return match.group(1).strip() if match else ""


def extract_section(block, field):
    pattern = (
        rf"(?ims)^\s*{re.escape(field)}\s*:\s*\n?"
        rf"(.*?)"
        rf"(?=^\s*[А-Яа-яЁёA-Za-z ]+\s*:|\Z)"
    )

    match = re.search(pattern, block)

    return match.group(1).strip() if match else ""


def load_recipes() -> list[Document]:
    if not DATA_FILE.exists():
        raise RecipeAIError(
            f"Не найден файл базы рецептов: {DATA_FILE}"
        )

    content = DATA_FILE.read_text(encoding="utf-8-sig")

    blocks = re.split(
        r"(?im)^\s*===\s*РЕЦЕПТ\s*===\s*$",
        content
    )

    documents = []

    for block in blocks:
        if not block.strip():
            continue

        title = extract_value(block, "Название")
        category = extract_value(block, "Категория")
        time_text = extract_value(block, "Время")
        difficulty = extract_value(block, "Сложность")

        ingredients = extract_section(block, "Ингредиенты")
        steps_text = extract_section(block, "Приготовление")

        if not title:
            continue

        time_match = re.search(r"\d+", time_text)
        time_minutes = int(time_match.group()) if time_match else 0

        ingredient_lines = [
            line.strip().lstrip("-• ").strip()
            for line in ingredients.splitlines()
            if line.strip()
        ]

        steps = [
            re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
            for line in steps_text.splitlines()
            if line.strip()
        ]

        metadata = {
            "title": title,
            "category": category,
            "time": time_minutes,
            "time_minutes": time_minutes,
            "difficulty": difficulty,
            "ingredients": ingredient_lines,
            "steps": steps,
        }

        page_content = (
                f"Название: {title}\n"
                f"Категория: {category}\n"
                f"Время: {time_minutes} минут\n"
                f"Сложность: {difficulty}\n"
                f"Ингредиенты:\n"
                + "\n".join(ingredient_lines)
                + "\nПриготовление:\n"
                + "\n".join(steps)
        )

        documents.append(
            Document(
                page_content=page_content,
                metadata=metadata
            )
        )

    if not documents:
        raise RecipeAIError(
            "Не удалось прочитать рецепты из data.txt. "
            "Проверь разделители === РЕЦЕПТ ===."
        )

    return documents


def get_llm():
    if not GEMINI_API_KEY:
        raise RecipeAIError(
            "Не найден GEMINI_API_KEY или GOOGLE_API_KEY в .env"
        )

    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.3,
    )


def ingredient_key(value):
    """Упрощённое сравнение русских названий продуктов."""

    text = normalize(value)

    text = re.sub(r"\s*[—–-].*$", "", text)
    text = re.sub(r"\d+", "", text)

    words = re.findall(r"[а-яёa-z]+", text)

    if not words:
        return ""

    word = words[0]

    aliases = {
        "яйца": "яйцо",
        "яиц": "яйцо",
        "яйцом": "яйцо",
        "помидоры": "помидор",
        "помидора": "помидор",
        "томаты": "помидор",
        "картошка": "картофель",
        "картошку": "картофель",
        "огурцы": "огурец",
        "огурца": "огурец",
        "яблоки": "яблоко",
        "бананы": "банан",
        "грибы": "гриб",
        "сливки": "сливки",
        "макароны": "макароны",
    }

    if word in aliases:
        return aliases[word]

    for ending in (
            "ами", "ями", "ого", "ему", "ыми",
            "ими", "ов", "ев", "ей", "ом",
            "ем", "ах", "ях", "ы", "и", "а", "я"
    ):
        if len(word) > len(ending) + 3 and word.endswith(ending):
            word = word[:-len(ending)]
            break

    return word


class RecipeAssistant:

    def __init__(self):
        self.documents = load_recipes()
        self.categories = self._get_categories()
        self.llm = None

    def _get_categories(self):
        categories = sorted({
            doc.metadata["category"]
            for doc in self.documents
            if doc.metadata["category"]
        })

        return categories

    def refresh(self):
        self.documents = load_recipes()
        self.categories = self._get_categories()

    def search(
            self,
            products=None,
            category="Любая",
            max_time=None
    ):
        product_list = parse_products(products)
        time_limit = parse_time_limit(max_time)
        selected_category = normalize(category or "Любая")

        results = []

        for doc in self.documents:
            meta = doc.metadata

            if (
                    selected_category not in ("любая", "any", "")
                    and normalize(meta["category"]) != selected_category
            ):
                continue

            if (
                    time_limit is not None
                    and meta["time_minutes"] > time_limit
            ):
                continue

            ingredients = meta["ingredients"]

            if product_list:
                ingredient_names = [
                    ingredient_key(item)
                    for item in ingredients
                ]

                matched = any(
                    ingredient_key(product) in ingredient_names
                    for product in product_list
                    if ingredient_key(product)
                )

                if not matched:
                    continue

            results.append(doc)

        return results

    def search_by_query(self, query):
        return self.search(products=query)

    def format_docs(self, documents):
        return "\n\n".join(
            doc.page_content for doc in documents
        )

    def ingredient_status(self, document, products=None):
        available = {
            ingredient_key(item)
            for item in parse_products(products)
        }

        result = []

        for line in document.metadata["ingredients"]:
            name = re.split(r"[—–-]", line)[0].strip()
            key = ingredient_key(name)

            result.append({
                "name": name,
                "line": line,
                "have": bool(key and key in available),
            })

        return result

    def recommend(
            self,
            products=None,
            category="Любая",
            max_time=None,
            docs=None
    ):

        results = docs if isinstance(docs, list) else self.search(
            products,
            category,
            max_time
        )

        if not results:
            return "Подходящих рецептов не найдено."

        recipes_text = self.format_docs(results[:3])

        prompt = f"""
Ты — помощник по приготовлению еды.

Используй только рецепты из базы.
Не придумывай новые рецепты и ингредиенты.

Для каждого рецепта укажи:
- Название
- Категорию
- Время
- Ингредиенты
- Пошаговое приготовление

Отвечай понятно на русском языке.

БАЗА РЕЦЕПТОВ:
{recipes_text}
"""

        try:
            if self.llm is None:
                self.llm = get_llm()

            response = self.llm.invoke(prompt)
            return response.content

        except Exception as error:

            return (
                    "Не удалось получить ответ Gemini. "
                    "Но вот найденные рецепты:\n\n"
                    + recipes_text
                    + f"\n\nОшибка: {error}"
            )

    def substitute(self, document, ingredient, products=None):
        prompt = f"""
В рецепте "{document.metadata['title']}"
нужно заменить ингредиент: {ingredient}.

Предложи подходящие варианты замены.
Отвечай на русском языке.
"""

        if self.llm is None:
            self.llm = get_llm()

        response = self.llm.invoke(prompt)
        return response.content

    def ask(self, question, docs=None, products=None):
        recipes = self.format_docs(docs or [])

        prompt = f"""
Ты помощник по приготовлению еды.
Отвечай на русском языке.

Вопрос пользователя: {question}

Контекст рецептов:
{recipes}
"""

        if self.llm is None:
            self.llm = get_llm()

        response = self.llm.invoke(prompt)
        return response.content

    def chef_advice(self, question):
        return self.ask(question)


app = FastAPI(
    title="Recipe AI",
    description="AI-помощник по рецептам",
    version="1.0.0"
)


class RecipeRequest(BaseModel):
    products: list[str] = Field(default_factory=list)
    category: str = "Любая"
    max_time: Optional[str] = None
    limit: int = 3


class QuestionRequest(BaseModel):
    question: str


assistant = RecipeAssistant()


@app.get("/")
def home():
    return {
        "message": "Recipe AI is running",
        "recipes_count": len(assistant.documents),
        "categories": assistant.categories
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/recipes")
def get_recipes():
    return [
        doc.metadata for doc in assistant.documents
    ]


@app.post("/recommend")
def recommend_recipes(request: RecipeRequest):
    try:
        docs = assistant.search(
            request.products,
            request.category,
            request.max_time
        )

        return {
            "recommendations": assistant.recommend(
                request.products,
                request.category,
                request.max_time,
                docs[:request.limit]
            )
        }

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/ask")
def ask_question(request: QuestionRequest):
    try:
        return {"answer": assistant.ask(request.question)}
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

