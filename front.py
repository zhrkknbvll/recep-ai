import inspect
import streamlit as st

from main import RecipeAssistant, RecipeAIError


st.set_page_config(
    page_title="Recipe AI",
    page_icon="🍳",
    layout="wide"
)


@st.cache_resource
def get_assistant():
    return RecipeAssistant()


try:
    assistant = get_assistant()
except Exception as error:
    st.error(f"Не удалось запустить RecipeAssistant: {error}")
    st.stop()

def call_method(method, values):

    signature = inspect.signature(method)

    parameters = signature.parameters

    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return method(**values)

    kwargs = {
        name: value
        for name, value in values.items()
        if name in parameters
    }

    return method(**kwargs)


def get_value(document, *names, default=None):

    if isinstance(document, dict):
        for name in names:
            if name in document:
                return document[name]

    for name in names:
        if hasattr(document, name):
            return getattr(document, name)

    return default


def normalize_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, str):
        return [value]

    return [value]


def get_ingredient_status(document, products):


    status = call_method(
        assistant.ingredient_status,
        {
            "doc": document,
            "document": document,
            "recipe": document,
            "products": products
        }
    )

    found = []
    missing = []

    if isinstance(status, dict):
        found = normalize_list(status.get("found", []))
        missing = normalize_list(status.get("missing", []))

    elif isinstance(status, list):
        for item in status:

            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("line")
                    or item.get("ingredient")
                    or "Ингредиент"
                )

                if item.get("have", False):
                    found.append(name)
                else:
                    missing.append(name)

            elif isinstance(item, str):
                missing.append(item)

    return found, missing


def get_recipe_name(document):
    return get_value(
        document,
        "name",
        "title",
        "Название",
        default="Рецепт"
    )


def get_recipe_category(document):
    return get_value(
        document,
        "category",
        "Категория",
        default="Не указана"
    )


def get_recipe_time(document):
    return get_value(
        document,
        "time",
        "minutes",
        "Время",
        default="Не указано"
    )


def get_recipe_difficulty(document):
    return get_value(
        document,
        "difficulty",
        "Сложность",
        default="Не указана"
    )


def get_recipe_ingredients(document):
    return normalize_list(
        get_value(
            document,
            "ingredients",
            "Ингредиенты",
            default=[]
        )
    )


def get_recipe_steps(document):
    return normalize_list(
        get_value(
            document,
            "instructions",
            "steps",
            "Приготовление",
            default=[]
        )
    )


# --------------------------------------------------
# ЗАГОЛОВОК
# --------------------------------------------------

st.title("🍳 Recipe AI")
st.write(
    "Найди рецепт по продуктам, которые есть у тебя дома."
)

st.divider()


# --------------------------------------------------
# БОКОВАЯ ПАНЕЛЬ
# --------------------------------------------------

st.sidebar.header("🔎 Поиск рецептов")

products_text = st.sidebar.text_input(
    "Какие продукты у тебя есть?",
    placeholder="Например: сыр, помидоры, яйца"
)

products = [
    product.strip()
    for product in products_text.split(",")
    if product.strip()
]


categories = getattr(assistant, "categories", [])

if not isinstance(categories, list):
    categories = list(categories)

category_options = ["Любая"] + [
    category
    for category in categories
    if category != "Любая"
]

selected_category = st.sidebar.selectbox(
    "Категория",
    category_options
)

time_options = {
    "Любое": None,
    "До 15 минут": 15,
    "До 30 минут": 30,
    "До 45 минут": 45,
    "До 1 часа": 60,
    "До 2 часов": 120
}

selected_time = st.sidebar.selectbox(
    "Время приготовления",
    list(time_options.keys())
)

max_time = time_options[selected_time]

search_button = st.sidebar.button(
    "🔍 Найти рецепты",
    use_container_width=True
)


# --------------------------------------------------
# СОСТОЯНИЕ ПРИЛОЖЕНИЯ
# --------------------------------------------------

if "recipes" not in st.session_state:
    st.session_state.recipes = []

if "searched" not in st.session_state:
    st.session_state.searched = False

if "chat" not in st.session_state:
    st.session_state.chat = []

if "ai_answers" not in st.session_state:
    st.session_state.ai_answers = {}


# --------------------------------------------------
# ПОИСК РЕЦЕПТОВ
# --------------------------------------------------

if search_button:

    if not products:
        st.warning("Сначала введи продукты через запятую.")

    else:
        try:
            with st.spinner("Ищем подходящие рецепты..."):

                docs = call_method(
                    assistant.search,
                    {
                        "products": products,
                        "category": selected_category,
                        "max_time": max_time
                    }
                )

                docs = normalize_list(docs)

                st.session_state.recipes = docs
                st.session_state.searched = True
                st.session_state.ai_answers = {}

        except RecipeAIError as error:
            st.error(f"Ошибка Recipe AI: {error}")

        except Exception as error:
            st.error(f"Ошибка поиска: {error}")


# --------------------------------------------------
# РЕЗУЛЬТАТЫ
# --------------------------------------------------

if st.session_state.searched:

    docs = st.session_state.recipes

    if not docs:
        st.warning(
            "Рецептов не найдено. Попробуй изменить продукты "
            "или снять фильтры."
        )

    else:
        st.success(f"Найдено рецептов: {len(docs)}")

        # Получаем рекомендации, если метод доступен.
        if hasattr(assistant, "recommend"):
            try:
                recommendations = call_method(
                    assistant.recommend,
                    {
                        "products": products,
                        "category": selected_category,
                        "max_time": max_time,
                        "docs": docs,
                        "documents": docs,
                        "limit": 3
                    }
                )

                if recommendations:
                    st.subheader("⭐ Рекомендации AI")
                    st.write(recommendations)

            except Exception:
                pass

        st.divider()

        for index, doc in enumerate(docs):

            name = get_recipe_name(doc)
            category = get_recipe_category(doc)
            recipe_time = get_recipe_time(doc)
            difficulty = get_recipe_difficulty(doc)

            with st.container(border=True):

                st.subheader(f"🍽️ {name}")

                col1, col2, col3 = st.columns(3)

                col1.write(f"📂 {category}")
                col2.write(f"⏱️ {recipe_time}")
                col3.write(f"⭐ {difficulty}")

                st.divider()


                st.markdown("### 🥕 Ингредиенты")

                found, missing = get_ingredient_status(
                    doc,
                    products
                )

                if found:
                    st.markdown("**Есть у тебя:**")

                    for ingredient in found:
                        st.write(f"✅ {ingredient}")

                if missing:
                    st.markdown("**Нужно купить:**")

                    for ingredient in missing:
                        st.write(f"❌ {ingredient}")

                ingredients = get_recipe_ingredients(doc)

                if ingredients:
                    with st.expander("Посмотреть все ингредиенты"):
                        for ingredient in ingredients:
                            st.write(f"• {ingredient}")

                # ----------------------------------
                # ПРИГОТОВЛЕНИЕ
                # ----------------------------------

                steps = get_recipe_steps(doc)

                with st.expander("👩‍🍳 Способ приготовления"):
                    for step_index, step in enumerate(steps, start=1):
                        if isinstance(step, dict):
                            step = (
                                step.get("text")
                                or step.get("description")
                                or str(step)
                            )

                        st.write(f"{step_index}. {step}")

                # ----------------------------------
                # AI-ПОМОЩНИК
                # ----------------------------------

                with st.expander("✨ Спросить AI об этом рецепте"):

                    question = st.text_input(
                        "Задай вопрос:",
                        key=f"question_{index}",
                        placeholder="Например: как сделать блюдо вкуснее?"
                    )

                    if st.button(
                        "Получить ответ",
                        key=f"ask_{index}"
                    ):

                        if not question.strip():
                            st.warning("Напиши вопрос.")

                        else:
                            try:
                                with st.spinner("AI думает..."):

                                    answer = call_method(
                                        assistant.ask,
                                        {
                                            "question": question,
                                            "docs": docs,
                                            "documents": docs,
                                            "products": products
                                        }
                                    )

                                    st.session_state.ai_answers[index] = answer

                            except Exception as error:
                                st.error(f"Ошибка AI: {error}")

                    if index in st.session_state.ai_answers:
                        st.info(
                            st.session_state.ai_answers[index]
                        )



                with st.expander("🔄 Заменить ингредиент"):

                    ingredient_options = [
                        str(item) for item in ingredients
                    ]

                    if ingredient_options:

                        selected_ingredient = st.selectbox(
                            "Выбери ингредиент",
                            ingredient_options,
                            key=f"ingredient_{index}"
                        )

                        if st.button(
                            "Найти замену",
                            key=f"substitute_{index}"
                        ):

                            try:
                                with st.spinner("Ищем замену..."):

                                    replacement = call_method(
                                        assistant.substitute,
                                        {
                                            "doc": doc,
                                            "document": doc,
                                            "recipe": doc,
                                            "ingredient": selected_ingredient,
                                            "products": products
                                        }
                                    )

                                    st.success("Вариант замены:")
                                    st.write(replacement)

                            except Exception as error:
                                st.error(
                                    f"Не удалось найти замену: {error}"
                                )

                    else:
                        st.info("Список ингредиентов отсутствует.")


st.divider()

st.header("💬 Чат с Recipe AI")

st.write(
    "Можешь задать вопрос о приготовлении еды, "
    "продуктах или рецептах."
)

for message in st.session_state.chat:

    with st.chat_message(message["role"]):
        st.write(message["content"])


user_question = st.chat_input(
    "Напиши свой вопрос..."
)

if user_question:

    st.session_state.chat.append(
        {
            "role": "user",
            "content": user_question
        }
    )

    with st.chat_message("user"):
        st.write(user_question)

    try:
        with st.chat_message("assistant"):

            with st.spinner("AI отвечает..."):

                answer = call_method(
                    assistant.ask,
                    {
                        "question": user_question,
                        "docs": st.session_state.recipes,
                        "documents": st.session_state.recipes,
                        "products": products
                    }
                )

                st.write(answer)

        st.session_state.chat.append(
            {
                "role": "assistant",
                "content": str(answer)
            }
        )

    except Exception as error:
        st.error(f"Ошибка чата: {error}")


st.divider()

st.caption(
    "Recipe AI — интеллектуальный помощник для поиска рецептов 🍳"
)