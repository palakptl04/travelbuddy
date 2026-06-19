import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from app import create_app
from config import TestingConfig
from app.extensions import db, bcrypt, login_manager
from app.models import User, Trip, TripMember
from datetime import date, timedelta

app = create_app(TestingConfig)

# Patch load_user to add logging
original_load_user = login_manager._user_callback
def patched_load_user(user_id):
    result = original_load_user(user_id)
    print(f'[load_user] called with user_id={user_id!r}, result={result}')
    return result
login_manager._user_callback = patched_load_user

# Push outer app context (simulates _clean_db)
ctx = app.app_context()
ctx.push()
db.create_all()

# Simulate auth_client
with app.app_context():
    pw1 = bcrypt.generate_password_hash('TestPass123!').decode()
    owner = User(name='Owner User', email='owner@example.com', password_hash=pw1)
    pw2 = bcrypt.generate_password_hash('Pass2!').decode()
    joiner = User(name='Joiner User', email='joiner@example.com', password_hash=pw2)
    db.session.add_all([owner, joiner])
    db.session.commit()
    owner_id = owner.id
    joiner_id = joiner.id
    print(f'Owner ID: {owner_id}, Joiner ID: {joiner_id}')

# Simulate auth_client HTTP login
owner_client = app.test_client()
owner_client.post('/auth/login', data={'email': 'owner@example.com', 'password': 'TestPass123!'}, follow_redirects=True)

# Re-fetch owner
with app.app_context():
    owner = db.session.get(User, owner_id)

# Simulate test body: create trip
with app.app_context():
    tomorrow = date.today() + timedelta(days=1)
    trip = Trip(owner_id=owner_id, title='Join Test Trip', destination='Rajkot',
                departure_city='Mumbai', start_date=tomorrow, end_date=tomorrow+timedelta(days=4),
                budget_min=3000, budget_max=8000, max_members=4, is_public=True)
    db.session.add(trip)
    db.session.commit()
    trip_id = trip.id
    print(f'trip_id={trip_id}')

# Use session_transaction to inject joiner
joiner_client = app.test_client()
with joiner_client.session_transaction() as sess:
    sess['_user_id'] = str(joiner_id)
    sess['_fresh'] = True

print(f'--- Making join request for trip_id={trip_id}, joiner_id={joiner_id} ---')
resp = joiner_client.post('/trips/{}/request'.format(trip_id), follow_redirects=False)
print(f'Response: {resp.status_code}, Location: {resp.headers.get("Location")}')

resp2 = joiner_client.post('/trips/{}/request'.format(trip_id), follow_redirects=True)
page = resp2.data.decode('utf-8', errors='replace')
print('Buddy sent:', 'Buddy request sent' in page)
print('Already sent:', 'already sent' in page)

with app.app_context():
    mem = TripMember.query.filter_by(trip_id=trip_id, user_id=joiner_id).first()
    print(f'TripMember: {mem}')
    all_mem = TripMember.query.all()
    print(f'All TripMembers: {all_mem}')

ctx.pop()
