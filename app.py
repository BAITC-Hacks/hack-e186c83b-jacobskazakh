import json
import os
import sqlite3
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "challenge_hub.db")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT NOT NULL,
            description TEXT NOT NULL, goal TEXT NOT NULL, deliverables TEXT NOT NULL,
            skills TEXT NOT NULL, timeline TEXT NOT NULL, budget TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', score INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, challenge_id INTEGER NOT NULL,
            student TEXT NOT NULL, idea TEXT NOT NULL, plan TEXT NOT NULL, link TEXT,
            status TEXT NOT NULL DEFAULT 'На рассмотрении', created_at TEXT NOT NULL,
            FOREIGN KEY(challenge_id) REFERENCES challenges(id)
        );
        """)


def score_card(c):
    fields = [("Цель", c.get("goal")), ("Результат", c.get("deliverables")),
              ("Навыки", c.get("skills")), ("Срок", c.get("timeline")),
              ("Бюджет/ресурсы", c.get("budget"))]
    filled = sum(bool(str(v or "").strip()) for _, v in fields)
    score = round(filled * 20)
    missing = [name for name, value in fields if not str(value or "").strip()]
    level = "Готова к публикации" if score >= 80 else "Нужно уточнить" if score >= 40 else "Черновик"
    return score, level, missing


def draft_questions(description):
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            response = OpenAI().chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0.3,
                messages=[{"role": "system", "content": "Ты помогаешь бизнесу оформить задачу для студенческого проекта. Ответь по-русски: краткий заголовок, затем ровно 5 конкретных уточняющих вопросов с нумерацией. Не выдумывай факты."},
                          {"role": "user", "content": description}],
            )
            return response.choices[0].message.content
        except Exception as exc:
            st.warning(f"AI временно недоступен; показаны базовые вопросы. ({exc})")
    return "1. Какую конкретную проблему нужно решить и для кого?\n2. Какой измеримый результат будет считаться успехом?\n3. Какие данные, технологии или ресурсы доступны команде?\n4. Какие навыки нужны участникам?\n5. Каковы желаемые сроки и ограничения по бюджету?"


def page_create():
    st.header("Опишите бизнес-задачу")
    with st.form("draft_form"):
        description = st.text_area("Черновик задачи", placeholder="Например: хотим лучше понимать отток клиентов", height=120)
        submitted = st.form_submit_button("Получить вопросы AI", type="primary")
    if submitted:
        if len(description.strip()) < 12:
            st.error("Добавьте немного контекста — хотя бы одно полное предложение.")
        else:
            st.session_state.description = description.strip()
            st.session_state.questions = draft_questions(description.strip())
    if st.session_state.get("questions"):
        st.subheader("Уточните задачу")
        st.markdown(st.session_state.questions)
        st.caption("Ответьте на вопросы и перенесите важные детали в поля карточки ниже.")
        with st.form("card_form"):
            title = st.text_input("Название", value="")
            company = st.text_input("Компания / владелец задачи", value="")
            goal = st.text_area("Цель и проблема", value=st.session_state.description)
            deliverables = st.text_area("Ожидаемый результат")
            skills = st.text_input("Тема / нужные навыки")
            timeline = st.text_input("Сроки")
            budget = st.text_input("Бюджет или доступные ресурсы")
            if st.form_submit_button("Рассчитать готовность"):
                card = dict(title=title, company=company, description=st.session_state.description,
                            goal=goal, deliverables=deliverables, skills=skills, timeline=timeline, budget=budget)
                st.session_state.card = card
    if st.session_state.get("card"):
        c = st.session_state.card
        score, level, missing = score_card(c)
        st.subheader("Предпросмотр карточки")
        st.metric("Готовность", f"{score}/100", level)
        if missing:
            st.info("Нужно добавить: " + ", ".join(missing))
        st.write(f"**{c['title'] or 'Без названия'}** · {c['company'] or 'Компания не указана'}")
        with st.form("publish_form"):
            c["title"] = st.text_input("Название", c["title"])
            c["company"] = st.text_input("Компания", c["company"])
            c["goal"] = st.text_area("Цель", c["goal"])
            c["deliverables"] = st.text_area("Ожидаемый результат", c["deliverables"])
            c["skills"] = st.text_input("Тема / навыки", c["skills"])
            c["timeline"] = st.text_input("Сроки", c["timeline"])
            c["budget"] = st.text_input("Бюджет / ресурсы", c["budget"])
            score, level, missing = score_card(c)
            st.caption(f"Рейтинг после редактирования: {score}/100 · {level}")
            confirm = st.form_submit_button("Подтвердить и опубликовать", type="primary")
        if confirm:
            score, level, missing = score_card(c)
            if not c["title"].strip() or not c["company"].strip():
                st.error("Заполните название и компанию.")
            elif score < 40:
                st.error("Добавьте сведения о цели и результате, чтобы опубликовать карточку.")
            else:
                with db() as conn:
                    conn.execute("INSERT INTO challenges(title,company,description,goal,deliverables,skills,timeline,budget,status,score,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (c["title"],c["company"],c["description"],c["goal"],c["deliverables"],c["skills"],c["timeline"],c["budget"],"published",score,datetime.now().isoformat(timespec="seconds")))
                st.session_state.pop("card", None)
                st.session_state.pop("questions", None)
                st.success("Задача опубликована в каталоге!")


def page_catalog():
    st.header("Каталог задач")
    with db() as conn:
        rows = conn.execute("SELECT * FROM challenges WHERE status='published' ORDER BY score DESC, id DESC").fetchall()
    if not rows:
        st.info("Здесь пока нет задач. Создайте первую на вкладке «Новая задача».")
        return
    topics = sorted({r["skills"] for r in rows if r["skills"]})
    topic = st.selectbox("Тема", ["Все темы"] + topics)
    min_score = st.slider("Минимальная готовность", 0, 100, 0, 10)
    shown = [r for r in rows if r["score"] >= min_score and (topic == "Все темы" or r["skills"] == topic)]
    sort = st.selectbox("Сортировка", ["Готовность: сначала высокая", "Новые сначала"])
    if sort == "Новые сначала":
        shown.reverse()
    for r in shown:
        with st.expander(f"{r['title']} · {r['score']}/100 · {r['company']}"):
            st.write(r["goal"])
            st.markdown(f"**Результат:** {r['deliverables'] or 'Не указан'}  \n**Тема:** {r['skills'] or 'Не указана'}  \n**Сроки:** {r['timeline'] or 'Не указаны'}  \n**Ресурсы:** {r['budget'] or 'Не указаны'}")
            with st.form(f"proposal_{r['id']}"):
                student = st.text_input("Ваше имя / команда")
                idea = st.text_area("Идея решения")
                plan = st.text_area("План работы")
                link = st.text_input("Ссылка на портфолио / материалы (необязательно)")
                if st.form_submit_button("Отправить предложение"):
                    if not student.strip() or not idea.strip() or not plan.strip():
                        st.error("Укажите имя, идею и план.")
                    else:
                        with db() as conn:
                            conn.execute("INSERT INTO proposals(challenge_id,student,idea,plan,link,created_at) VALUES(?,?,?,?,?,?)",
                                         (r["id"],student.strip(),idea.strip(),plan.strip(),link.strip(),datetime.now().isoformat(timespec="seconds")))
                        st.success("Предложение отправлено бизнесу.")


def page_proposals():
    st.header("Отклики от студентов")
    with db() as conn:
        rows = conn.execute("SELECT p.*, c.title AS challenge_title FROM proposals p JOIN challenges c ON c.id=p.challenge_id ORDER BY p.id DESC").fetchall()
    if not rows:
        st.info("Пока нет откликов.")
        return
    for p in rows:
        with st.container(border=True):
            st.subheader(f"{p['challenge_title']} — {p['student']}")
            st.write(f"**Идея:** {p['idea']}\n\n**План:** {p['plan']}")
            if p["link"]:
                st.markdown(f"[Материалы команды]({p['link']})")
            status = st.selectbox("Решение бизнеса", ["На рассмотрении", "Принять", "Отклонить"], index=["На рассмотрении", "Принять", "Отклонить"].index(p["status"]), key=f"status_{p['id']}")
            if status != p["status"]:
                with db() as conn:
                    conn.execute("UPDATE proposals SET status=? WHERE id=?", (status, p["id"]))
                st.rerun()


def main():
    st.set_page_config(page_title="AI Sana Challenge Hub", page_icon="🧩", layout="wide")
    init_db()
    st.title("🧩 AI Sana Challenge Hub")
    st.caption("Превращайте короткие бизнес-задачи в понятные проекты для студенческих команд.")
    page = st.radio("Раздел", ["Новая задача", "Каталог", "Отклики"], horizontal=True, label_visibility="collapsed")
    if page == "Новая задача":
        page_create()
    elif page == "Каталог":
        page_catalog()
    else:
        page_proposals()


if __name__ == "__main__":
    main()
