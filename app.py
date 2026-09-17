import time
from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# cors_allowed_origins="*" позволяет подключаться с вашего GitHub Pages
socketio = SocketIO(app, cors_allowed_origins="*")

# --- БАЗА ДАННЫХ ВОПРОСОВ ---
QUESTIONS = [
    {
        "id": 1,
        "text": "Сколько спутников у Юпитера (по данным на 2026 год)?",
        "options": ["79", "95", "12", "48"],
        "correct": 1 # Индекс правильного ответа (95)
    },
    {
        "id": 2,
        "text": "Какой язык программирования мы используем для бэкенда?",
        "options": ["PHP", "JavaScript", "Python", "C++"],
        "correct": 2 # Python
    }
]

# --- СОСТОЯНИЕ ИГРЫ (GAME STATE) ---
game_state = {
    "status": "LOBBY", # LOBBY, QUESTION, PAUSE, FINISHED
    "current_q_index": 0,
    "q_start_time": 0,
    "players": {}, # { socket_id: {"name": "Имя", "score": 0, "answered": False} }
    "admin_sid": None
}

# --- ПОДДКЛЮЧЕНИЕ / ОТКЛЮЧЕНИЕ ---
@socketio.on('connect')
def handle_connect():
    print(f"Новое подключение: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in game_state["players"]:
        del game_state["players"][sid]
        broadcast_lobby()
    if sid == game_state["admin_sid"]:
        game_state["admin_sid"] = None
    print(f"Отключение: {sid}")

# --- 1. АВТОРИЗАЦИЯ И ВХОД ---
@socketio.on('login')
def handle_login(data):
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()
    sid = request.sid

    if code == 'God':
        game_state["admin_sid"] = sid
        game_state["players"][sid] = {"name": f"{name} (Ведущий)", "score": 0, "answered": True, "is_admin": True}
        emit('login_response', {'success': True, 'is_admin': True})
        broadcast_lobby()

    elif code == 'FS':
        if not name:
            emit('login_response', {'success': False, 'message': 'Введите имя!'})
            return
        game_state["players"][sid] = {"name": name, "score": 0, "answered": False, "is_admin": False}
        emit('login_response', {'success': True, 'is_admin': False})
        broadcast_lobby()

    else:
        emit('login_response', {'success': False, 'message': 'Неверный пароль!'})

def broadcast_lobby():
    # Отправляем всем актуальный список игроков
    players_list = [{"name": p["name"], "score": p["score"]} for p in game_state["players"].values()]
    socketio.emit('update_lobby', {
        'players': players_list,
        'status': game_state["status"]
    })

# --- 2. УПРАВЛЕНИЕ ИГРОЙ (ТОЛЬКО ДЛЯ АДМИНА) ---
@socketio.on('admin_start_question')
def handle_start_question():
    if request.sid != game_state["admin_sid"]:
        return # Игнорируем, если жмет не админ

    idx = game_state["current_q_index"]
    if idx >= len(QUESTIONS):
        # Вопросы кончились -> Финал
        game_state["status"] = "FINISHED"
        send_final_results()
        return

    q_data = QUESTIONS[idx]
    game_state["status"] = "QUESTION"
    game_state["q_start_time"] = time.time()
    
    # Сбрасываем флаг ответа у всех участников
    for p in game_state["players"].values():
        p["answered"] = False

    # Отправляем вопрос ВСЕМ (без поля 'correct'!)
    socketio.emit('show_question', {
        'q_num': idx + 1,
        'total_q': len(QUESTIONS),
        'text': q_data['text'],
        'options': q_data['options'],
        'timer': 30
    })

# --- 3. ПРИЕМ ОТВЕТОВ И МАТЕМАТИКА БАЛЛОВ ---
@socketio.on('submit_answer')
def handle_submit_answer(data):
    sid = request.sid
    player = game_state["players"].get(sid)

    # Проверки: зарегин ли игрок, идет ли вопрос и не отвечал ли он уже
    if not player or game_state["status"] != "QUESTION" or player["answered"] or player.get("is_admin"):
        return

    selected_option = data.get('option_index')
    now = time.time()
    time_taken = now - game_state["q_start_time"] # За сколько секунд ответил
    time_left = max(0, 30 - time_taken) # Сколько секунд оставалось (из 30)

    player["answered"] = True
    
    # Считаем потенциальный бонус за скорость (от 0 до 100)
    speed_bonus = 100 * (time_left / 30.0)

    correct_option = QUESTIONS[game_state["current_q_index"]]["correct"]

    if selected_option == correct_option:
        # ПРАВИЛЬНО: 100 базовых + весь бонус за скорость
        points = 100 + speed_bonus
    else:
        # НЕПРАВИЛЬНО: 0 базовых + 50% от бонуса за скорость
        points = speed_bonus * 0.5

    player["score"] += round(points)

    # Отправляем игроку подтверждение, что ответ принят
    emit('answer_accepted', {'score_added': round(points)})

    # Проверяем, сколько человек ответило
    check_all_answered()

def check_all_answered():
    total_players = [p for p in game_state["players"].values() if not p.get("is_admin")]
    answered_players = [p for p in total_players if p["answered"]]

    # Рассылаем всем счетчик: "Ответили 5 из 10"
    socketio.emit('progress_update', {
        'answered': len(answered_players),
        'total': len(total_players)
    })

@socketio.on('admin_next_round')
def handle_next_round():
    if request.sid != game_state["admin_sid"]:
        return
    game_state["current_q_index"] += 1
    handle_start_question()

def send_final_results():
    # Сортируем игроков по очкам
    leaderboard = sorted(
        [{"name": p["name"], "score": p["score"]} for p in game_state["players"].values() if not p.get("is_admin")],
        key=lambda x: x["score"],
        reverse=True
    )
    socketio.emit('show_results', {'leaderboard': leaderboard})

if __name__ == '__main__':
    # Запуск сервера локально на порту 5000
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
