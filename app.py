import os
import time
from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

TOTAL_QUESTIONS = 12  # Всего вопросов в квизе

# --- СОСТОЯНИЕ ИГРЫ ---
game_state = {
    "status": "LOBBY",  # LOBBY, QUESTION, PAUSE, FINISHED
    "current_q_index": 0,
    "q_start_time": 0,
    "players": {},  # { socket_id: {"name": "Имя", "score": 0, "answered": False, "is_admin": False} }
    "admin_sid": None
}

# --- ПОДКЛЮЧЕНИЕ / ОТКЛЮЧЕНИЕ ---
@socketio.on('connect')
def handle_connect():
    print(f"Новое подключение: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in game_state["players"]:
        del game_state["players"][sid]
        broadcast_lobby()
        if game_state["status"] == "QUESTION":
            check_all_answered()
    if sid == game_state["admin_sid"]:
        game_state["admin_sid"] = None
    print(f"Отключение: {sid}")

# --- 1. ВХОД И АВТОРИЗАЦИЯ ---
@socketio.on('login')
def handle_login(data):
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()
    sid = request.sid

    if code == 'God':
        game_state["admin_sid"] = sid
        host_name = name if name else "Богдан"
        game_state["players"][sid] = {"name": f"{host_name} — Ведущий", "score": 0, "answered": True, "is_admin": True}
        emit('login_response', {'success': True, 'is_admin': True})
        broadcast_lobby()

    elif code == 'FS':
        if not name:
            emit('login_response', {'success': False, 'message': 'Введите имя!'})
            return
        game_state["players"][sid] = {"name": name, "score": 0, "answered": False, "is_admin": False}
        emit('login_response', {'success': True, 'is_admin': False})
        broadcast_lobby()
        if game_state["status"] == "QUESTION":
            check_all_answered()

    else:
        emit('login_response', {'success': False, 'message': 'Неверный пароль!'})

def broadcast_lobby():
    players_list = [{"name": p["name"], "score": p["score"]} for p in game_state["players"].values()]
    socketio.emit('update_lobby', {
        'players': players_list,
        'status': game_state["status"]
    })

# --- 2. УПРАВЛЕНИЕ РАУНДАМИ ---
@socketio.on('admin_start_question')
def handle_start_question():
    if request.sid != game_state["admin_sid"]:
        return

    idx = game_state["current_q_index"]
    if idx >= TOTAL_QUESTIONS:
        game_state["status"] = "FINISHED"
        send_final_results()
        return

    game_state["status"] = "QUESTION"
    game_state["q_start_time"] = time.time()
    
    # Сбрасываем флаг ответа у всех участников для нового вопроса
    for p in game_state["players"].values():
        p["answered"] = False

    socketio.emit('show_question', {
        'q_num': idx + 1,
        'total_q': TOTAL_QUESTIONS,
        'timer': 30
    })

    # Сразу мгновенно сбрасываем счетчик на экранах: "Ответили: 0 из N"
    check_all_answered()

# --- 3. ПРИЕМ ФЛАГА И РАСЧЕТ БАЛЛОВ ---
@socketio.on('submit_answer')
def handle_submit_answer(data):
    sid = request.sid
    player = game_state["players"].get(sid)

    if not player or game_state["status"] != "QUESTION" or player["answered"] or player.get("is_admin"):
        return

    is_correct = bool(data.get('is_correct', False))
    now = time.time()
    time_taken = now - game_state["q_start_time"]
    time_left = max(0, 30 - time_taken)

    player["answered"] = True
    speed_bonus = 100 * (time_left / 30.0)

    if is_correct:
        points = 100 + speed_bonus
    else:
        points = speed_bonus * 0.5

    player["score"] += round(points)

    emit('answer_accepted', {'score_added': round(points)})
    check_all_answered()

def check_all_answered():
    total_players = [p for p in game_state["players"].values() if not p.get("is_admin")]
    answered_players = [p for p in total_players if p["answered"]]

    socketio.emit('progress_update', {
        'answered': len(answered_players),
        'total': len(total_players)
    })

@socketio.on('admin_next_round')
def handle_next_round():
    if request.sid != game_state["admin_sid"]:
        return

    # ФИКС: Если старт происходит из ЛОББИ — запускаем вопрос №1 (индекс 0), иначе прибавляем +1
    if game_state["status"] == "LOBBY":
        game_state["current_q_index"] = 0
    else:
        game_state["current_q_index"] += 1

    handle_start_question()

# --- 4. ЗАВЕРШЕНИЕ СЕССИИ И ОПРЕДЕЛЕНИЕ ПОБЕДИТЕЛЯ ---
@socketio.on('admin_end_session')
def handle_end_session():
    if request.sid != game_state["admin_sid"]:
        return
    
    winner_name = "Все гости"
    non_admin_players = [p for p in game_state["players"].values() if not p.get("is_admin")]
    if non_admin_players:
        winner = max(non_admin_players, key=lambda x: x["score"])
        winner_name = winner["name"]

    socketio.emit('session_ended', {'winner_name': winner_name})

    game_state["status"] = "LOBBY"
    game_state["current_q_index"] = 0
    game_state["q_start_time"] = 0
    game_state["players"] = {}
    game_state["admin_sid"] = None

def send_final_results():
    leaderboard = sorted(
        [{"name": p["name"], "score": p["score"]} for p in game_state["players"].values() if not p.get("is_admin")],
        key=lambda x: x["score"],
        reverse=True
    )
    socketio.emit('show_results', {'leaderboard': leaderboard})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
