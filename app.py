import io
import csv
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, jsonify, Response, abort
)
from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import extract, func
from dotenv import load_dotenv

from config import Config
from models import db, User, Expense, Category, Budget, utcnow
from forms import (
    RegisterForm, LoginForm, ExpenseForm, BudgetForm, ProfileForm, CategoryForm
)

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Войдите, чтобы продолжить"
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------- Вспомогательное ----------
MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


@app.template_filter("month_ru")
def month_ru(value):
    try:
        year, month = str(value).split("-")
        return f"{MONTH_NAMES_RU[int(month)]} {year}"
    except (ValueError, KeyError, AttributeError):
        return value


def owner_required(model):
    """Декоратор: проверяет, что объект с request.args/path принадлежит текущему юзеру."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            obj_id = kwargs.get("expense_id") or kwargs.get("cat_id") or kwargs.get("budget_id")
            obj = db.session.get(model, obj_id)
            if not obj or obj.user_id != current_user.id:
                abort(404)
            return fn(obj, *args, **kwargs)
        return wrapper
    return deco


def _month_bounds(month_str):
    year, month = map(int, month_str.split("-"))
    return year, month


# ---------- Аутентификация ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        if User.query.filter_by(username=username).first():
            flash("Пользователь уже существует", "danger")
            return redirect(url_for("register"))

        user = User(
            username=username,
            password_hash=generate_password_hash(form.password.data),
        )
        db.session.add(user)
        db.session.flush()

        default_cats = [
            ("Еда", "expense"), ("Транспорт", "expense"), ("Жильё", "expense"),
            ("Развлечения", "expense"), ("Здоровье", "expense"),
            ("Одежда", "expense"), ("Прочее", "expense"),
            ("Зарплата", "income"), ("Подработка", "income"),
        ]
        for name, _t in default_cats:
            db.session.add(Category(name=name, user_id=user.id))

        db.session.commit()
        flash("Регистрация успешна! Войдите в систему.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        flash("Неверный логин или пароль", "danger")

    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        if not check_password_hash(current_user.password_hash, form.old_password.data):
            flash("Текущий пароль неверный", "danger")
        else:
            current_user.password_hash = generate_password_hash(form.new_password.data)
            db.session.commit()
            flash("Пароль обновлён", "success")
            return redirect(url_for("profile"))
    return render_template("profile.html", form=form)


# ---------- Дашборд ----------
@app.route("/")
@login_required
def index():
    month_param = request.args.get("month")
    page = request.args.get("page", 1, type=int)
    search = (request.args.get("q") or "").strip()

    base_query = Expense.query.filter_by(user_id=current_user.id)
    if month_param:
        try:
            year, month = _month_bounds(month_param)
            base_query = base_query.filter(
                extract("year", Expense.created_at) == year,
                extract("month", Expense.created_at) == month,
            )
        except ValueError:
            flash("Некорректный формат месяца", "warning")
            month_param = None

    if search:
        base_query = base_query.filter(Expense.description.ilike(f"%{search}%"))

    all_expenses = base_query.all()
    income = sum(e.amount for e in all_expenses if e.type == "income")
    outcome = sum(e.amount for e in all_expenses if e.type == "expense")
    balance = income - outcome

    by_category = {}
    for e in all_expenses:
        if e.type == "expense":
            by_category[e.category.name] = by_category.get(e.category.name, 0) + e.amount

    # Пагинация вручную (уже отсортировано по created_at desc)
    sorted_expenses = sorted(all_expenses, key=lambda e: e.created_at, reverse=True)
    per_page = 15
    total_pages = max(1, (len(sorted_expenses) + per_page - 1) // per_page)
    page = min(page, total_pages)
    expenses_page = sorted_expenses[(page - 1) * per_page: page * per_page]

    monthly_data = (
        db.session.query(
            func.strftime("%Y-%m", Expense.created_at).label("month"),
            func.sum(Expense.amount),
        )
        .filter(Expense.user_id == current_user.id, Expense.type == "expense")
        .group_by("month")
        .order_by(func.strftime("%Y-%m", Expense.created_at).desc())
        .limit(6)
        .all()
    )
    monthly_data = list(reversed(monthly_data))

    current_month_str = utcnow().strftime("%Y-%m")
    budgets = Budget.query.filter_by(
        user_id=current_user.id, month=current_month_str
    ).all()
    budgets_info = []
    for b in budgets:
        spent = sum(
            e.amount for e in Expense.query.filter_by(
                user_id=current_user.id,
                category_id=b.category_id,
                type="expense",
            ).filter(
                extract("year", Expense.created_at) == int(current_month_str[:4]),
                extract("month", Expense.created_at) == int(current_month_str[5:]),
            ).all()
        )
        percent = min(100, int((spent / b.limit_amount) * 100)) if b.limit_amount > 0 else 0
        budgets_info.append({
            "category_name": b.category.name,
            "limit": b.limit_amount,
            "spent": spent,
            "percent": percent,
            "over": spent > b.limit_amount,
        })

    all_dates = db.session.query(Expense.created_at).filter_by(
        user_id=current_user.id
    ).all()
    available_months = sorted(
        {d[0].strftime("%Y-%m") for d in all_dates if d[0]}, reverse=True
    )

    return render_template(
        "index.html",
        expenses=expenses_page,
        income=income,
        outcome=outcome,
        balance=balance,
        by_category=by_category,
        available_months=available_months,
        selected_month=month_param,
        current_month=current_month_str,
        monthly_data=monthly_data,
        budgets_info=budgets_info,
        page=page,
        total_pages=total_pages,
        search=search,
    )


# ---------- Аналитика ----------
@app.route("/analytics")
@login_required
def analytics():
    month_param = request.args.get("month")
    query = Expense.query.filter_by(user_id=current_user.id, type="expense")
    if month_param:
        try:
            year, month = _month_bounds(month_param)
            query = query.filter(
                extract("year", Expense.created_at) == year,
                extract("month", Expense.created_at) == month,
            )
        except ValueError:
            pass

    expenses = query.all()
    total = sum(e.amount for e in expenses) or 0

    by_category = {}
    for e in expenses:
        by_category[e.category.name] = by_category.get(e.category.name, 0) + e.amount

    top5 = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:5]

    by_day = {}
    for e in expenses:
        day = e.created_at.strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0) + e.amount

    days_count = len(by_day) or 1
    avg_per_day = total / days_count
    max_day = max(by_day.items(), key=lambda x: x[1]) if by_day else ("—", 0)

    all_dates = db.session.query(Expense.created_at).filter_by(
        user_id=current_user.id
    ).all()
    available_months = sorted(
        {d[0].strftime("%Y-%m") for d in all_dates if d[0]}, reverse=True
    )

    return render_template(
        "analytics.html",
        total=total,
        top5=top5,
        avg_per_day=avg_per_day,
        max_day=max_day,
        by_day=sorted(by_day.items()),
        selected_month=month_param,
        available_months=available_months,
    )


# ---------- API ----------
@app.route("/api/chart/category")
@login_required
def api_chart_category():
    month_param = request.args.get("month")
    query = Expense.query.filter_by(user_id=current_user.id, type="expense")
    if month_param:
        try:
            year, month = _month_bounds(month_param)
            query = query.filter(
                extract("year", Expense.created_at) == year,
                extract("month", Expense.created_at) == month,
            )
        except ValueError:
            pass

    by_category = {}
    for e in query.all():
        by_category[e.category.name] = by_category.get(e.category.name, 0) + e.amount

    return jsonify({"labels": list(by_category.keys()), "values": list(by_category.values())})


# ---------- Расходы ----------
@app.route("/add", methods=["GET", "POST"])
@login_required
def add_expense():
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = ExpenseForm()
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        expense = Expense(
            amount=form.amount.data,
            type=form.type.data,
            category_id=form.category_id.data,
            description=form.description.data or "",
            user_id=current_user.id,
        )
        db.session.add(expense)
        db.session.commit()
        flash("Запись добавлена", "success")
        return redirect(url_for("index"))

    return render_template("add_expense.html", form=form)


@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if not expense or expense.user_id != current_user.id:
        abort(404)

    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = ExpenseForm(obj=expense)
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        expense.amount = form.amount.data
        expense.type = form.type.data
        expense.category_id = form.category_id.data
        expense.description = form.description.data or ""
        db.session.commit()
        flash("Запись обновлена", "success")
        return redirect(url_for("index"))

    return render_template("edit_expense.html", form=form, expense=expense)


@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if expense and expense.user_id == current_user.id:
        db.session.delete(expense)
        db.session.commit()
        flash("Запись удалена", "info")
    month = request.form.get("month") or request.args.get("month")
    return redirect(url_for("index", month=month) if month else url_for("index"))


# ---------- Категории ----------
@app.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Category.query.filter_by(user_id=current_user.id, name=name).first():
            flash("Такая категория уже есть", "warning")
        else:
            db.session.add(Category(name=name, user_id=current_user.id))
            db.session.commit()
            flash("Категория добавлена", "success")
            return redirect(url_for("categories"))

    user_categories = Category.query.filter_by(
        user_id=current_user.id
    ).order_by(Category.name).all()
    return render_template("categories.html", categories=user_categories, form=form)


@app.route("/categories/delete/<int:cat_id>", methods=["POST"])
@login_required
def delete_category(cat_id):
    category = Category.query.filter_by(id=cat_id, user_id=current_user.id).first()
    if category:
        if Expense.query.filter_by(category_id=cat_id).first():
            flash("Нельзя удалить категорию с существующими записями", "danger")
        else:
            db.session.delete(category)
            db.session.commit()
            flash("Категория удалена", "info")
    return redirect(url_for("categories"))


# ---------- Бюджеты ----------
@app.route("/budgets")
@login_required
def budgets():
    user_budgets = Budget.query.filter_by(
        user_id=current_user.id
    ).order_by(Budget.month.desc()).all()
    return render_template("budgets.html", budgets=user_budgets)


@app.route("/budgets/add", methods=["GET", "POST"])
@login_required
def add_budget():
    categories = Category.query.filter_by(user_id=current_user.id).order_by(Category.name).all()
    form = BudgetForm()
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        month = form.month.data.strip()
        try:
            datetime.strptime(month, "%Y-%m")
        except ValueError:
            flash("Месяц должен быть в формате YYYY-MM", "danger")
            return redirect(url_for("add_budget"))

        existing = Budget.query.filter_by(
            user_id=current_user.id,
            category_id=form.category_id.data,
            month=month,
        ).first()
        if existing:
            flash("Бюджет на этот месяц и категорию уже создан", "warning")
        else:
            db.session.add(Budget(
                user_id=current_user.id,
                category_id=form.category_id.data,
                limit_amount=form.limit_amount.data,
                month=month,
            ))
            db.session.commit()
            flash("Бюджет создан", "success")
        return redirect(url_for("budgets"))

    current_month = utcnow().strftime("%Y-%m")
    form.month.data = form.month.data or current_month
    return render_template("add_budget.html", form=form, current_month=current_month)


@app.route("/budgets/delete/<int:budget_id>", methods=["POST"])
@login_required
def delete_budget(budget_id):
    budget = db.session.get(Budget, budget_id)
    if budget and budget.user_id == current_user.id:
        db.session.delete(budget)
        db.session.commit()
        flash("Бюджет удалён", "info")
    return redirect(url_for("budgets"))


# ---------- Экспорт CSV ----------
@app.route("/export/csv")
@login_required
def export_csv():
    rows = (
        Expense.query.filter_by(user_id=current_user.id)
        .order_by(Expense.created_at.desc())
        .all()
    )
    output = io.StringIO()
    output.write("\ufeff")  # BOM для Excel
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Дата", "Тип", "Категория", "Описание", "Сумма (₽)"])
    for e in rows:
        writer.writerow([
            e.created_at.strftime("%Y-%m-%d %H:%M"),
            "Доход" if e.type == "income" else "Расход",
            e.category.name,
            e.description or "",
            f"{e.amount:.2f}".replace(".", ","),
        ])

    filename = f"expenses_{utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------- Ошибки ----------
@app.errorhandler(404)
def not_found(e):
    return render_template("base.html", not_found=True), 404


# ---------- Инициализация ----------
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)