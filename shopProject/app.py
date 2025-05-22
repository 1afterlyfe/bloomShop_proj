from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from datetime import datetime, UTC
from flask_bcrypt import Bcrypt
from functools import wraps
from flask import g
from sqlalchemy import func
from sqlalchemy.orm import validates
from sensData import *

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bloomshop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = MAIL_USERNAME
app.config['MAIL_PASSWORD'] = MAIL_PASSWORD
app.config['MAIL_DEFAULT_SENDER'] = MAIL_DEFAULT_SENDER

db = SQLAlchemy(app)
mail = Mail(app)
bcrypt = Bcrypt(app)


class Flower(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    size = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(50), nullable=True)
    season = db.Column(db.String(50), nullable=True)
    image_url = db.Column(db.String(200), nullable=True)

    @property
    def average_rating(self):
        avg = db.session.query(func.avg(Review.rating)).filter(
            Review.flower_id == self.id
        ).scalar()
        return round(avg, 1) if avg else None

    @property
    def review_count(self):
        return db.session.query(func.count(Review.id)).filter(
            Review.flower_id == self.id
        ).scalar()


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    flower_id = db.Column(db.Integer, db.ForeignKey('flower.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(UTC))

    user = db.relationship('User', backref='reviews')
    flower = db.relationship('Flower', backref='reviews')

    # Додаємо валідацію рейтингу
    @validates('rating')
    def validate_rating(self, key, rating):
        if not 1 <= rating <= 5:
            raise ValueError('Rating must be between 1 and 5')
        return rating

class FlowerCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    flower_id = db.Column(db.Integer, db.ForeignKey('flower.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    status = db.Column(db.String(50), default='cart')
    total_price = db.Column(db.Float, default=0.0)
    delivery_method = db.Column(db.String(50), nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)
    address = db.Column(db.Text, nullable=True)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(UTC))
    user = db.relationship('User', backref='orders')
    items = db.relationship('OrderItem', backref='order', lazy=True)

    CART = 'cart'
    ACCEPTED = 'accepted'
    PROCESSING = 'processing'
    SHIPPED = 'shipped'
    DELIVERED = 'delivered'
    CANCELLED = 'cancelled'

    def recalculate_total(self):
        """Перераховує загальну суму кошика на основі елементів."""
        self.total_price = sum(item.price * item.quantity for item in self.items)
        db.session.commit()

def get_or_create_cart():
    if g.user:
        cart = Order.query.filter_by(user_id=g.user.id, status='cart').first()
        if not cart:
            cart = Order(user_id=g.user.id, status='cart')
            db.session.add(cart)
            db.session.commit()
        return cart
    else:
        cart_id = session.get('cart_id')
        if cart_id:
            cart = db.session.get(Order, cart_id)
            if cart and cart.status == 'cart':
                return cart
            session.pop('cart_id', None)

        cart = Order(status='cart')
        db.session.add(cart)
        db.session.commit()
        session['cart_id'] = cart.id
        return cart


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    flower_id = db.Column(db.Integer, db.ForeignKey('flower.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    password = db.Column(db.String(60), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            return render_template('error.html', error='Доступ дозволено лише адміністраторам.')
        return f(*args, **kwargs)

    return decorated_function


@app.before_request
def load_user():
    g.user = None
    if 'user_id' in session:
        g.user = User.query.get(session['user_id'])


@app.route('/')
def index():
    popular_flowers = Flower.query.limit(4).all()
    categories = Category.query.all()
    return render_template('index.html', flowers=popular_flowers, categories=categories)


@app.route('/flowers')
def flowers():
    search_query = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    color = request.args.get('color', '')
    season = request.args.get('season', '')
    price_min = request.args.get('price_min', type=float)
    price_max = request.args.get('price_max', type=float)
    min_rating = request.args.get('min_rating', type=float)

    query = Flower.query

    if search_query:
        query = query.filter(func.lower(Flower.name).contains(search_query.lower()))
    if category_id:
        query = query.join(FlowerCategory).filter(FlowerCategory.category_id == category_id)
    if color:
        query = query.filter(Flower.color == color)
    if season:
        query = query.filter(Flower.season == season)
    if price_min is not None:
        query = query.filter(Flower.price >= price_min)
    if price_max is not None:
        query = query.filter(Flower.price <= price_max)
    if min_rating is not None:
        query = query.join(Review).group_by(Flower.id).having(
            func.avg(Review.rating) >= min_rating)

    page = request.args.get('page', 1, type=int)
    per_page = 8
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    all_flowers = pagination.items

    categories = Category.query.all()
    colors = [c[0] for c in db.session.query(Flower.color).distinct().filter(Flower.color != None).all()]
    seasons = [s[0] for s in db.session.query(Flower.season).distinct().filter(Flower.season != None).all()]

    return render_template(
        'flowers.html',
        flowers=all_flowers,
        pagination=pagination,
        categories=categories,
        colors=colors,
        seasons=seasons,
        current_filters={
            'search': search_query,
            'category': category_id,
            'color': color,
            'season': season,
            'price_min': price_min,
            'price_max': price_max,
            'min_rating': min_rating
        }
    )

@app.route('/flower/<int:flower_id>')
def flower(flower_id):
    flower = Flower.query.get_or_404(flower_id)

    category_ids = db.session.query(FlowerCategory.category_id).filter(FlowerCategory.flower_id == flower_id).all()
    category_ids = [cid[0] for cid in category_ids]
    categories = Category.query.filter(Category.id.in_(category_ids)).all()

    return render_template('flower.html', flower=flower, categories=categories)


@app.route('/add_to_cart/<int:flower_id>', methods=['POST'])
def add_to_cart(flower_id):
    flower = Flower.query.get_or_404(flower_id)
    cart = get_or_create_cart()

    # Перевіряємо, чи є вже цей товар у кошику
    existing_item = OrderItem.query.filter_by(order_id=cart.id, flower_id=flower_id).first()
    if existing_item:
        existing_item.quantity += 1
    else:
        new_item = OrderItem(
            order_id=cart.id,
            flower_id=flower.id,
            quantity=1,
            price=flower.price
        )
        db.session.add(new_item)

    cart.recalculate_total()
    return redirect(url_for('flowers'))


@app.route('/cart')
def cart():
    cart = get_or_create_cart()
    if not cart:
        return render_template('cart.html', cart_items=[], total_price=0.0)

    cart_items = []
    for item in cart.items:
        flower = db.session.get(Flower, item.flower_id)
        if flower:
            cart_items.append({
                'flower_id': item.flower_id,
                'name': flower.name,
                'price': item.price,
                'quantity': item.quantity,
                'image_url': flower.image_url or '/static/images/placeholder.jpg',
                'subtotal': item.price * item.quantity
            })
    total_price = cart.total_price or 0.0
    return render_template('cart.html', cart_items=cart_items, total_price=total_price)


@app.route('/cart/update/<int:flower_id>', methods=['POST'])
def update_cart(flower_id):
    cart = get_or_create_cart()
    new_quantity = request.form.get('quantity', type=int)

    if new_quantity and new_quantity >= 1:
        item = OrderItem.query.filter_by(order_id=cart.id, flower_id=flower_id).first()
        if item:
            item.quantity = new_quantity
            db.session.commit()
            cart.recalculate_total()
    return redirect(url_for('cart'))


@app.route('/checkout', methods=['GET', 'POST'])
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = get_or_create_cart()
    if not cart.items:
        return redirect(url_for('cart'))

    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    if request.method == 'POST':
        name = request.form.get('name') if not user else user.name
        email = request.form.get('email') if not user else user.email
        phone = request.form.get('phone') if not user else user.phone
        address = request.form.get('address') if not user else user.address
        delivery_method = request.form.get('delivery_method')
        payment_method = request.form.get('payment_method')

        cart.status = 'accepted'
        cart.delivery_method = delivery_method
        cart.payment_method = payment_method
        cart.address = address
        cart.email = email
        cart.user_id = user_id if user_id else cart.user_id
        db.session.commit()

        try:
            msg = Message(
                subject=f'BloomShop - Підтвердження замовлення №{cart.id}',
                recipients=[email],
                body=f"""
                Дякуємо за ваше замовлення, {name}!

                Замовлення №{cart.id}
                Статус: Прийнято
                Загальна сума: {cart.total_price} грн
                Адреса доставки: {address}
                Спосіб доставки: {delivery_method}
                Спосіб оплати: {payment_method}

                Деталі замовлення:
                {chr(10).join([f"- {Flower.query.get(item.flower_id).name} (x{item.quantity}): {item.price * item.quantity} грн" for item in cart.items])}

                Ми зв'яжемося з вами для підтвердження.
                """
            )
            mail.send(msg)

            if not user_id:
                session.pop('cart_id', None)
            return render_template('order_confirmation.html', order_id=cart.id, email_sent=True)
        except Exception as e:
            db.session.rollback()
            return render_template('order_confirmation.html', order_id=cart.id, email_sent=False, error=str(e))

    return render_template('checkout.html', user=user)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        password = request.form.get('password')

        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='Email уже зареєстровано.')

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(name=name, email=email, phone=phone, address=address, password=hashed_password)

        try:
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id

            msg = Message(
                subject='Ласкаво просимо до BloomShop!',
                recipients=[email],
                body=f"""
                             Шановний(а) {name},

                             Вітаємо з успішною реєстрацією в BloomShop!
                             Ваш email: {email}

                             Тепер ви можете:
                             - Переглядати наш каталог квітів
                             - Зберігати товари в кошику
                             - Отримувати персоналізовані пропозиції

                             Дякуємо, що приєдналися до нас!
                             Команда BloomShop
                             """
            )
            mail.send(msg)

            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            return render_template('register.html', error=str(e))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            session['user_id'] = user.id

            if 'cart_id' in session:
                temp_cart = Order.query.get(session['cart_id'])
                if temp_cart and temp_cart.status == 'cart':
                    user_cart = Order.query.filter_by(user_id=user.id, status='cart').first()
                    if not user_cart:
                        user_cart = Order(user_id=user.id, status='cart')
                        db.session.add(user_cart)
                        db.session.commit()
                    for item in temp_cart.items:
                        existing_item = OrderItem.query.filter_by(
                            order_id=user_cart.id, flower_id=item.flower_id
                        ).first()
                        if existing_item:
                            existing_item.quantity += item.quantity
                        else:
                            new_item = OrderItem(
                                order_id=user_cart.id,
                                flower_id=item.flower_id,
                                quantity=item.quantity,
                                price=item.price
                            )
                            db.session.add(new_item)
                        db.session.delete(item)
                    user_cart.recalculate_total()
                    db.session.delete(temp_cart)
                    session.pop('cart_id', None)
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Невірний email або пароль.')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('cart_id', None)
    return redirect(url_for('index'))


@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.filter(Order.status.in_(['accepted', 'processing', 'shipped', 'delivered', 'cancelled'])).all()
    return render_template('admin_orders.html', orders=orders)


@app.route('/admin/order/<int:order_id>/update', methods=['GET', 'POST'])
@admin_required
def admin_order_update(order_id):
    order = Order.query.get_or_404(order_id)
    statuses = [
        Order.ACCEPTED,
        Order.PROCESSING,
        Order.SHIPPED,
        Order.DELIVERED,
        Order.CANCELLED
    ]
    if request.method == 'POST':
        new_status = request.form.get('status')
        if new_status in statuses:
            old_status = order.status
            order.status = new_status
            try:
                db.session.commit()
                email = order.email or (order.user.email if order.user else None)
                if email:
                    msg = Message(
                        subject=f'BloomShop - Оновлення статусу замовлення №{order.id}',
                        recipients=[email],
                        body=f"""
                        Шановний(а) клієнт(е),

                        Статус вашого замовлення №{order.id} змінено з "{old_status}" на "{new_status}".
                        Загальна сума: {order.total_price} грн
                        Адреса доставки: {order.address}

                        Дякуємо за покупку в BloomShop!
                        """
                    )
                    mail.send(msg)
                flash('Статус замовлення успішно змінено!', 'success')
                return redirect(url_for('admin_orders'))
            except Exception as e:
                db.session.rollback()
                return render_template('admin_order_update.html', order=order, statuses=statuses, error=str(e))
    return render_template('admin_order_update.html', order=order, statuses=statuses)

@app.route('/flower/<int:flower_id>/add_review', methods=['POST'])
def add_review(flower_id):
    Flower.query.get_or_404(flower_id)

    if request.method == 'POST':
        rating = request.form.get('rating', type=int)
        comment = request.form.get('comment', '').strip()

        # check on existing feedback
        existing_review = Review.query.filter_by(
            user_id=session['user_id'],
            flower_id=flower_id
        ).first()

        if existing_review:
            flash('Ви вже залишали відгук для цієї квітки', 'warning')
            return redirect(url_for('flower', flower_id=flower_id))

        try:
            new_review = Review(
                user_id=session['user_id'],
                flower_id=flower_id,
                rating=rating,
                comment=comment
            )
            db.session.add(new_review)
            db.session.commit()
            flash('Ваш відгук успішно додано!', 'success')
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            flash('Сталася помилка при додаванні відгуку', 'danger')

        return redirect(url_for('flower', flower_id=flower_id))

@app.route('/clear_cart', methods=['POST'])
def clear_cart():
    cart = get_or_create_cart()

    OrderItem.query.filter_by(order_id=cart.id).delete()

    cart.total_price = 0
    db.session.commit()

    return redirect(url_for('cart'))

@app.route('/cleanup_carts')
@admin_required
def cleanup_carts():
    threshold = datetime.now(UTC) - timedelta(days=3)
    old_carts = Order.query.filter(
        Order.status == 'cart',
        Order.created_at < threshold
    ).all()

    if not old_carts:
        flash('Немає застарілих кошиків для видалення.', 'info')
        logger.info('No outdated carts to delete.')
    else:
        cart_count = len(old_carts)
        for cart in old_carts:
            OrderItem.query.filter_by(order_id=cart.id).delete()
            db.session.delete(cart)
        db.session.commit()
        flash(f'Успішно видалено {cart_count} застарілих кошиків.', 'success')
        logger.info(f'Deleted {cart_count} outdated cart(s).')

    return redirect(url_for('admin_orders'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
