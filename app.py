import json
import os
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "challenge_hub.db")

READINESS_LEVELS = [
    (0, 39, "Черновик · нужно уточнить"),
    (40, 69, "Рабочая"),
    (70, 89, "Готовая"),
    (90, 100, "Приоритетная"),
]
REVIEW_STATUSES = ["На рассмотрении", "Выбрать", "Отклонить"]
CARD_FIELDS = [
    ("Контекст и потребность", 20),
    ("Данные и материалы", 20),
    ("Ожидаемый результат", 15),
    ("Критерии успеха", 15),
    ("Ограничения", 10),
    ("Пользователи", 10),
    ("Связь с бизнесом", 10),
]
AI_SYSTEM_PROMPT = (
    "Помоги представителю бизнеса уточнить задачу для студенческой команды. "
    "Задавай только вопросы о неизвестном. Не делай предположений и не добавляй факты. "
    'Верни JSON вида {"questions":["...", "...", "..."]} с пятью краткими, '
    "конкретными вопросами на русском языке."
)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            company TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL DEFAULT '', deliverables TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '', timeline TEXT NOT NULL DEFAULT '',
            budget TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
            score INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL,
            student TEXT NOT NULL, idea TEXT NOT NULL, plan TEXT NOT NULL,
            link TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'На рассмотрении',
            created_at TEXT NOT NULL,
            FOREIGN KEY(challenge_id) REFERENCES challenges(id)
        );
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            interests TEXT NOT NULL DEFAULT '', skills TEXT NOT NULL DEFAULT '',
            technologies TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        """)
        _add_columns(conn, "challenges", {
            "industry": "TEXT NOT NULL DEFAULT ''",
            "need": "TEXT NOT NULL DEFAULT ''",
            "users": "TEXT NOT NULL DEFAULT ''",
            "data": "TEXT NOT NULL DEFAULT ''",
            "restrictions": "TEXT NOT NULL DEFAULT ''",
            "success_criteria": "TEXT NOT NULL DEFAULT ''",
            "contact": "TEXT NOT NULL DEFAULT ''",
            "interaction_mode": "TEXT NOT NULL DEFAULT ''",
            "demo_key": "TEXT",
        })
        _add_columns(conn, "proposals", {
            "timeline": "TEXT NOT NULL DEFAULT ''",
            "points": "INTEGER NOT NULL DEFAULT 0",
            "demo_key": "TEXT",
        })
        conn.execute("UPDATE proposals SET status='Выбрать' WHERE status='Принять'")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS challenges_demo_key ON challenges(demo_key)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS proposals_demo_key ON proposals(demo_key)")


def _add_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def readiness_level(score):
    for low, high, label in READINESS_LEVELS:
        if low <= score <= high:
            return label
    return READINESS_LEVELS[-1][2]


def score_card(card):
    """Score only information the business has entered and confirmed."""
    c = dict(card)
    breakdown = []

    context = bool(str(c.get("goal", "")).strip())
    need = bool(str(c.get("need", "")).strip())
    context_score = 20 if context and need else 10 if context or need else 0
    breakdown.append(("Контекст и потребность", context_score, 20))
    data = bool(str(c.get("data", "")).strip())
    breakdown.append(("Данные и материалы", 20 if data else 0, 20))
    for label, key, weight in [
        ("Ожидаемый результат", "deliverables", 15),
        ("Критерии успеха", "success_criteria", 15),
        ("Ограничения", "restrictions", 10),
        ("Пользователи", "users", 10),
    ]:
        breakdown.append((label, weight if str(c.get(key, "")).strip() else 0, weight))
    contact = bool(str(c.get("contact", "")).strip())
    interaction = bool(str(c.get("interaction_mode", "")).strip())
    business_score = (5 if contact else 0) + (5 if interaction else 0)
    breakdown.append(("Связь с бизнесом", business_score, 10))

    score = sum(points for _, points, _ in breakdown)
    missing = [label for label, points, possible in breakdown if points < possible]
    return score, readiness_level(score), missing, breakdown


def draft_questions(description):
    """Ask AI for structured clarification questions; safely fall back locally."""
    fallback = [
        "Что происходит сейчас и какую потребность нужно закрыть?",
        "Кто будет пользоваться результатом и как решают задачу сегодня?",
        "Какие данные, примеры или материалы можно предоставить команде?",
        "Какой конкретный результат ожидается и как измерить успех?",
        "Какие есть сроки, технологические ограничения и формат связи с бизнесом?",
    ]
    if not os.getenv("OPENAI_API_KEY"):
        return fallback, "локальный шаблон"
    try:
        from openai import OpenAI

        response = OpenAI().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": description},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        questions = payload.get("questions", [])
        questions = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
        if len(questions) >= 3:
            return questions[:5], "AI"
    except Exception:
        pass
    return fallback, "локальный шаблон (AI недоступен или вернул некорректный ответ)"


def demo_data():
    return [
        {
            "title": "Сократить время обработки заказов", "company": "Sana Market",
            "industry": "Розничная торговля", "goal": "Сейчас сотрудники вручную сверяют заказы и остатки.",
            "need": "Нужно уменьшить время обработки заказов в пиковые часы.",
            "users": "Сотрудники склада и менеджеры интернет-магазина.",
            "data": "Обезличенные CSV с заказами и остатками за три месяца.",
            "restrictions": "Срок четыре недели; использовать только тестовую выгрузку.",
            "deliverables": "Интерактивный прототип панели контроля очереди заказов.",
            "success_criteria": "На тестовом наборе время обработки сокращается минимум на 15%.",
            "contact": "business@example.test", "interaction_mode": "Еженедельная консультация по 30 минут.",
            "skills": "Аналитика, автоматизация", "timeline": "4 недели", "budget": "Тестовые данные и ментор",
        },
        {
            "title": "Понятнее показывать статус доставки", "company": "Qadam Logistics",
            "industry": "Логистика", "goal": "Клиенты часто уточняют статус доставки по телефону.",
            "need": "Хотим сократить число повторных вопросов о доставке.",
            "users": "Покупатели небольших интернет-магазинов.",
            "data": "Есть обезличенные статусы отправлений и временные метки.",
            "restrictions": "Не подключаться к рабочей системе; только прототип.",
            "deliverables": "Прототип страницы отслеживания посылки.",
            "success_criteria": "", "contact": "", "interaction_mode": "",
            "skills": "UX, веб-разработка", "timeline": "3 недели", "budget": "Интервью с сотрудником",
        },
        {
            "title": "Снизить списание продуктов", "company": "Dala Foods",
            "industry": "Производство", "goal": "В нескольких точках регулярно списываются продукты.",
            "need": "Нужно раньше замечать риск избыточного заказа.",
            "users": "Администраторы кафе.", "data": "Пример таблицы заказов доступен после согласования.",
            "restrictions": "Черновая идея; формат пилота обсудим.",
            "deliverables": "", "success_criteria": "", "contact": "", "interaction_mode": "",
            "skills": "Анализ данных", "timeline": "Не определён", "budget": "",
        },
        {
            "title": "Помочь новым клиентам освоить сервис", "company": "Ornek Digital",
            "industry": "Цифровые сервисы", "goal": "", "need": "Новые клиенты не всегда находят нужные функции.",
            "users": "", "data": "", "restrictions": "Без доступа к персональным данным.",
            "deliverables": "Кликабельный сценарий знакомства с сервисом.",
            "success_criteria": "Проверить понятность на пяти тестовых пользователях.",
            "contact": "", "interaction_mode": "",
            "skills": "Продуктовый дизайн", "timeline": "2 недели", "budget": "Тестовая среда",
        },
        {
            "title": "Собрать идеи для доступной городской среды", "company": "Open Qala",
            "industry": "Городская среда", "goal": "", "need": "Хотим узнать, какие участки маршрута требуют улучшения.",
            "users": "Жители района.", "data": "", "restrictions": "",
            "deliverables": "Карта наблюдений и приоритизированный список проблем.",
            "success_criteria": "", "contact": "", "interaction_mode": "",
            "skills": "Картография, исследование", "timeline": "",
            "budget": "Работа с открытыми данными",
        },
    ]


def seed_demo_data():
    teams = [
        ("Steppe Coders", "городские сервисы, логистика", "Python, аналитика", "Streamlit, SQL"),
        ("Nomad UX", "доступность, исследования", "UX, интервью", "Figma, прототипирование"),
        ("Data Qadam", "торговля, прогнозирование", "аналитика, ML", "Python, pandas"),
        ("Orta Lab", "образование, цифровые продукты", "дизайн, фронтенд", "Figma, HTML"),
        ("Aqyl Tech", "автоматизация, логистика", "backend, интеграции", "Python, SQLite"),
    ]
    proposal_rows = [
        ("Steppe Coders", "Сделать видимой очередь заказов и подсветить узкие места.", "Согласовать метрики, исследовать CSV, собрать прототип.", "3 недели"),
        ("Nomad UX", "Сгруппировать наблюдения жителей по маршрутам.", "Подготовить форму, проверить сценарий, собрать карту.", "2 недели"),
        ("Data Qadam", "Показать ранние сигналы лишнего заказа.", "Проверить поля данных, построить базовые графики.", "3 недели"),
        ("Orta Lab", "Добавить короткое интерактивное знакомство.", "Наметить путь пользователя и протестировать прототип.", "2 недели"),
        ("Aqyl Tech", "Собрать простой экран статуса доставки.", "Описать состояния и подготовить кликабельный макет.", "2 недели"),
    ]
    inserted = {"tasks": 0, "teams": 0, "proposals": 0}
    with db() as conn:
        now = datetime.now().isoformat(timespec="seconds")
        for index, team in enumerate(teams, 1):
            cur = conn.execute(
                "INSERT OR IGNORE INTO teams(name,interests,skills,technologies,created_at) VALUES(?,?,?,?,?)",
                (*team, now),
            )
            inserted["teams"] += cur.rowcount

        for index, card in enumerate(demo_data(), 1):
            key = f"demo-task-{index}"
            row = conn.execute("SELECT id FROM challenges WHERE demo_key=?", (key,)).fetchone()
            if row:
                challenge_id = row["id"]
            else:
                score, _, _, _ = score_card(card)
                cur = conn.execute("""
                    INSERT INTO challenges(
                        title,company,description,goal,deliverables,skills,timeline,budget,
                        status,score,created_at,industry,need,users,data,restrictions,
                        success_criteria,contact,interaction_mode,demo_key
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    card["title"], card["company"], card["goal"], card["goal"],
                    card["deliverables"], card["skills"], card["timeline"], card["budget"],
                    "published", score, now, card["industry"], card["need"], card["users"],
                    card["data"], card["restrictions"], card["success_criteria"],
                    card["contact"], card["interaction_mode"], key,
                ))
                challenge_id = cur.lastrowid
                inserted["tasks"] += 1

            proposal_key = f"demo-proposal-{index}"
            exists = conn.execute("SELECT 1 FROM proposals WHERE demo_key=?", (proposal_key,)).fetchone()
            if not exists:
                team_name, idea, plan, timeline = proposal_rows[index - 1]
                conn.execute("""
                    INSERT INTO proposals(challenge_id,student,idea,plan,link,status,created_at,timeline,points,demo_key)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                """, (challenge_id, team_name, idea, plan, "https://example.test/prototype",
                      "На рассмотрении", now, timeline, 0, proposal_key))
                inserted["proposals"] += 1
    return inserted


def _card_values():
    return {
        "title": st.session_state.card_title.strip(),
        "company": st.session_state.card_company.strip(),
        "description": st.session_state.description,
        "industry": st.session_state.card_industry.strip(),
        "goal": st.session_state.card_goal.strip(),
        "need": st.session_state.card_need.strip(),
        "users": st.session_state.card_users.strip(),
        "data": st.session_state.card_data.strip(),
        "restrictions": st.session_state.card_restrictions.strip(),
        "deliverables": st.session_state.card_deliverables.strip(),
        "success_criteria": st.session_state.card_success.strip(),
        "contact": st.session_state.card_contact.strip(),
        "interaction_mode": st.session_state.card_interaction.strip(),
        "skills": st.session_state.card_skills.strip(),
        "timeline": st.session_state.card_timeline.strip(),
        "budget": st.session_state.card_budget.strip(),
    }


def _save_card(card):
    score, level, missing, breakdown = score_card(card)
    st.session_state.card = card
    st.session_state.card_score = score
    st.session_state.card_level = level
    st.session_state.card_missing = missing
    st.session_state.card_breakdown = breakdown


def page_create():
    st.header("Превратите потребность в задачу")
    with st.expander("Формула рейтинга задачи"):
        st.caption("Баллы начисляются за сведения, которые представитель бизнеса внёс и подтвердил.")
        for label, weight in CARD_FIELDS:
            st.write(f"- **{label}: {weight} баллов**")
        st.caption("Уровни: 0–39 — черновик; 40–69 — рабочая; 70–89 — готовая; 90–100 — приоритетная. Любой опубликованный уровень виден в каталоге.")

    with st.form("draft_form"):
        description = st.text_area("Кратко опишите потребность или проблему", height=120,
                                   placeholder="Например: клиенты часто звонят узнать статус доставки")
        submitted = st.form_submit_button("Найти, что уточнить", type="primary")
    if submitted:
        if len(description.strip()) < 12:
            st.error("Добавьте контекст — хотя бы одно полное предложение.")
        else:
            st.session_state.description = description.strip()
            questions, source = draft_questions(description.strip())
            st.session_state.questions = questions
            st.session_state.question_source = source
            for key, value in {
                "card_title": "", "card_company": "", "card_industry": "",
                "card_goal": description.strip(), "card_need": "", "card_users": "",
                "card_data": "", "card_restrictions": "", "card_deliverables": "",
                "card_success": "", "card_contact": "", "card_interaction": "",
                "card_skills": "", "card_timeline": "", "card_budget": "",
            }.items():
                st.session_state[key] = value
            st.session_state.pop("card", None)

    if not st.session_state.get("questions"):
        return

    st.subheader("Уточняющие вопросы")
    st.caption(f"Источник: {st.session_state.get('question_source', 'AI')}. Ответьте и подтвердите сведения в карточке.")
    for index, question in enumerate(st.session_state.questions, 1):
        st.write(f"{index}. {question}")
    with st.expander("Промпт AI"):
        st.code(AI_SYSTEM_PROMPT)

    with st.form("card_form"):
        st.subheader("Карточка задачи")
        st.text_input("Название задачи *", key="card_title")
        st.text_input("Компания / владелец", key="card_company")
        st.text_input("Отрасль или тема", key="card_industry")
        st.text_area("Контекст: что происходит сейчас", key="card_goal")
        st.text_area("Потребность: что нужно изменить", key="card_need")
        st.text_area("Для кого создаётся решение", key="card_users")
        st.text_area("Данные и доступные материалы", key="card_data")
        st.text_area("Ограничения: сроки, технологии, доступы", key="card_restrictions")
        st.text_area("Ожидаемый результат", key="card_deliverables")
        st.text_area("Критерии успеха: как измерить результат", key="card_success")
        st.text_input("Контакт представителя бизнеса", key="card_contact")
        st.text_input("Формат взаимодействия и обратной связи", key="card_interaction")
        st.text_input("Навыки или технологии", key="card_skills")
        st.text_input("Сроки", key="card_timeline")
        st.text_input("Бюджет или доступные ресурсы", key="card_budget")
        saved = st.form_submit_button("Подтвердить сведения и пересчитать рейтинг", type="primary")
    if saved:
        _save_card(_card_values())

    card = st.session_state.get("card")
    if not card:
        st.info("Заполните карточку и подтвердите сведения, чтобы увидеть рейтинг.")
        return
    score = st.session_state.card_score
    st.subheader("Предпросмотр и рейтинг")
    st.metric("Качество задачи", f"{score}/100", st.session_state.card_level)
    for label, points, possible in st.session_state.card_breakdown:
        st.write(f"{'✅' if points == possible else '➕'} **{label}: {points}/{possible}**")
    if st.session_state.card_missing:
        st.info("Чтобы повысить рейтинг, уточните: " + ", ".join(st.session_state.card_missing))
    st.write(f"**{card['title'] or 'Без названия'}** · {card['company'] or 'Компания не указана'}")
    if st.button("Подтвердить и опубликовать в общем каталоге", type="primary"):
        if not card["title"]:
            st.error("Укажите название задачи перед публикацией.")
        else:
            with db() as conn:
                conn.execute("""
                    INSERT INTO challenges(
                        title,company,description,goal,deliverables,skills,timeline,budget,
                        status,score,created_at,industry,need,users,data,restrictions,
                        success_criteria,contact,interaction_mode
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    card["title"], card["company"], card["description"], card["goal"],
                    card["deliverables"], card["skills"], card["timeline"], card["budget"],
                    "published", score, datetime.now().isoformat(timespec="seconds"),
                    card["industry"], card["need"], card["users"], card["data"],
                    card["restrictions"], card["success_criteria"], card["contact"],
                    card["interaction_mode"],
                ))
            for key in list(st.session_state):
                if key in {"card", "card_score", "card_level", "card_missing", "card_breakdown", "questions", "question_source", "description"}:
                    del st.session_state[key]
            st.success("Задача опубликована. Её рейтинг определяет место в каталоге, а не доступность для студентов.")


def page_catalog():
    st.header("Открытый каталог задач")
    with db() as conn:
        rows = conn.execute("SELECT * FROM challenges WHERE status='published' ORDER BY score DESC, created_at DESC, id DESC").fetchall()
    if not rows:
        st.info("Опубликованных задач пока нет. Создайте свою или загрузите демо-данные в разделе «Команды».")
        return
    topics = sorted({r["industry"] for r in rows if r["industry"]})
    left, right = st.columns(2)
    with left:
        topic = st.selectbox("Тема", ["Все темы"] + topics)
    with right:
        level = st.selectbox("Уровень готовности", ["Все уровни"] + [item[2] for item in READINESS_LEVELS])
    shown = [r for r in rows if (topic == "Все темы" or r["industry"] == topic)
             and (level == "Все уровни" or readiness_level(r["score"]) == level)]
    st.caption("Задачи доступны всем командам. Сначала показаны карточки с более высоким рейтингом; низкий рейтинг не закрывает отклики.")
    for row in shown:
        label = f"{row['title']} · {row['score']}/100 · {row['company']}"
        with st.expander(label):
            st.caption(f"{readiness_level(row['score'])} · {row['industry'] or 'Тема не указана'}")
            st.write(f"**Контекст:** {row['goal'] or 'Не указан'}\n\n**Потребность:** {row['need'] or 'Не указана'}")
            st.markdown(
                f"**Пользователи:** {row['users'] or 'Не указаны'}  \n"
                f"**Данные:** {row['data'] or 'Не указаны'}  \n"
                f"**Ограничения:** {row['restrictions'] or 'Не указаны'}  \n"
                f"**Ожидаемый результат:** {row['deliverables'] or 'Не указан'}  \n"
                f"**Критерии успеха:** {row['success_criteria'] or 'Не указаны'}  \n"
                f"**Навыки:** {row['skills'] or 'Не указаны'}  ·  **Сроки:** {row['timeline'] or 'Не указаны'}"
            )
            if row["score"] < 40:
                st.warning("Черновик: бизнесу стоит уточнить детали. Команда всё равно может откликнуться.")
            with st.form(f"proposal_{row['id']}"):
                student = st.text_input("Название команды")
                idea = st.text_area("Идея решения")
                plan = st.text_area("План работы")
                timeline = st.text_input("Предполагаемый срок")
                link = st.text_input("Ссылка на прототип или материалы (необязательно)")
                if st.form_submit_button("Отправить предложение"):
                    if not student.strip() or not idea.strip() or not plan.strip():
                        st.error("Укажите команду, идею и план.")
                    else:
                        with db() as conn:
                            conn.execute("""
                                INSERT INTO proposals(challenge_id,student,idea,plan,link,status,created_at,timeline)
                                VALUES(?,?,?,?,?,?,?,?)
                            """, (row["id"], student.strip(), idea.strip(), plan.strip(), link.strip(),
                                  "На рассмотрении", datetime.now().isoformat(timespec="seconds"), timeline.strip()))
                        st.success("Предложение отправлено. Решение остаётся за представителем бизнеса.")


def page_proposals():
    st.header("Предложения команд")
    st.caption("Бизнес вручную выбирает несколько команд, отклоняет их или пока не принимает решение.")
    with db() as conn:
        rows = conn.execute("""
            SELECT p.*, c.title AS challenge_title, c.company AS company
            FROM proposals p JOIN challenges c ON c.id=p.challenge_id
            ORDER BY c.score DESC, p.id DESC
        """).fetchall()
    if not rows:
        st.info("Пока нет откликов. Команды могут отправить предложение из каталога.")
        return
    for proposal in rows:
        with st.container(border=True):
            st.subheader(f"{proposal['challenge_title']} — {proposal['student']}")
            st.caption(f"Бизнес: {proposal['company']} · Статус: {proposal['status']} · Баллы команды: {proposal['points']}")
            st.markdown(
                f"**Идея:** {proposal['idea']}\n\n**План:** {proposal['plan']}\n\n"
                f"**Срок:** {proposal['timeline'] or 'Не указан'}"
            )
            if proposal["link"]:
                st.markdown(f"[Прототип или материалы]({proposal['link']})")
            status = st.selectbox(
                "Решение бизнеса", REVIEW_STATUSES,
                index=REVIEW_STATUSES.index(proposal["status"]), key=f"status_{proposal['id']}",
            )
            if status != proposal["status"]:
                with db() as conn:
                    conn.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal["id"]))
                st.rerun()
            if proposal["status"] == "Выбрать":
                if st.button("Подтвердить этап и начислить 10 баллов", key=f"progress_{proposal['id']}"):
                    with db() as conn:
                        conn.execute("UPDATE proposals SET points=points+10 WHERE id=? AND status='Выбрать'", (proposal["id"],))
                    st.success("Подтверждённый этап записан: команде начислено 10 баллов.")
                    st.rerun()


def page_teams():
    st.header("Команды и демо-данные")
    if st.button("Загрузить синтетический набор для демо", type="primary"):
        inserted = seed_demo_data()
        st.success(
            f"Демо-набор проверен: новых задач — {inserted['tasks']}, "
            f"профилей команд — {inserted['teams']}, предложений — {inserted['proposals']}. "
            "Повторная загрузка не создаёт копии."
        )
    with db() as conn:
        teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    st.subheader(f"Профили команд ({len(teams)})")
    if not teams:
        st.info("Профилей пока нет. Загрузите синтетический набор для демонстрации.")
    for team in teams:
        with st.container(border=True):
            st.subheader(team["name"])
            st.write(f"**Интересы:** {team['interests']}\n\n**Навыки:** {team['skills']}\n\n**Технологии:** {team['technologies']}")
    with st.expander("Добавить профиль команды"):
        with st.form("team_form"):
            name = st.text_input("Название команды")
            interests = st.text_input("Интересы")
            skills = st.text_input("Навыки")
            technologies = st.text_input("Технологии")
            if st.form_submit_button("Сохранить профиль"):
                if not name.strip():
                    st.error("Укажите название команды.")
                else:
                    try:
                        with db() as conn:
                            conn.execute("INSERT INTO teams(name,interests,skills,technologies,created_at) VALUES(?,?,?,?,?)",
                                         (name.strip(), interests.strip(), skills.strip(), technologies.strip(),
                                          datetime.now().isoformat(timespec="seconds")))
                        st.success("Профиль команды сохранён.")
                    except sqlite3.IntegrityError:
                        st.error("Команда с таким названием уже существует.")


def main():
    st.set_page_config(page_title="AI Sana Challenge Hub", page_icon="🧩", layout="wide")
    init_db()
    st.title("🧩 AI Sana Challenge Hub")
    st.caption("Полезнее задача — выше рейтинг. Команды выбирают задачи сами, бизнес выбирает команды вручную.")
    page = st.radio("Раздел", ["Новая задача", "Каталог", "Отклики", "Команды"], horizontal=True,
                    label_visibility="collapsed")
    if page == "Новая задача":
        page_create()
    elif page == "Каталог":
        page_catalog()
    elif page == "Отклики":
        page_proposals()
    else:
        page_teams()


if __name__ == "__main__":
    main()
