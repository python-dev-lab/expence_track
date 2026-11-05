from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FloatField, SelectField, DateField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, EqualTo


class RegisterForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired(), Length(min=3, max=40)])
    password = PasswordField("Пароль", validators=[DataRequired(), Length(min=6, max=128)])
    confirm = PasswordField("Повтор пароля", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Зарегистрироваться")


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired()])
    password = PasswordField("Пароль", validators=[DataRequired()])
    submit = SubmitField("Войти")


class ExpenseForm(FlaskForm):
    amount = FloatField("Сумма, ₽", validators=[DataRequired(), NumberRange(min=0.01)])
    type = SelectField(
        "Тип",
        choices=[("expense", "Расход"), ("income", "Доход")],
        validators=[DataRequired()],
    )
    category_id = SelectField("Категория", coerce=int, validators=[DataRequired()])
    description = StringField("Описание", validators=[Optional(), Length(max=200)])
    submit = SubmitField("Сохранить")


class BudgetForm(FlaskForm):
    category_id = SelectField("Категория", coerce=int, validators=[DataRequired()])
    month = StringField("Месяц (YYYY-MM)", validators=[DataRequired(), Length(min=7, max=7)])
    limit_amount = FloatField("Лимит, ₽", validators=[DataRequired(), NumberRange(min=0.01)])
    submit = SubmitField("Создать")


class ProfileForm(FlaskForm):
    old_password = PasswordField("Текущий пароль", validators=[DataRequired()])
    new_password = PasswordField("Новый пароль", validators=[DataRequired(), Length(min=6)])
    submit = SubmitField("Сменить пароль")


class CategoryForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired(), Length(min=1, max=50)])
    submit = SubmitField("Добавить")