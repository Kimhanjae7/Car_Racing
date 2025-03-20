import os
import gymnasium as gym
import numpy as np
import pygame  
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.monitor import Monitor

# Pygame 초기화
pygame.init()
screen = pygame.display.set_mode((400, 300))  
pygame.display.set_caption("HIL Control Window")

# 모델 및 로그 저장 폴더 설정
MODEL_DIR = "sac_hil_model_v0"
LOG_DIR = "tensorboard_logs"
MODEL_PATH = os.path.join(MODEL_DIR, "sac_car_racing_best")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# CarRacing 환경 생성
env = gym.make("CarRacing-v3", domain_randomize=False, render_mode="human")
env = Monitor(env)
env = DummyVecEnv([lambda: env])

# 기존 모델 불러오기 or 새로운 모델 생성
try:
    model = SAC.load(MODEL_PATH, env=env, tensorboard_log=LOG_DIR)
    print(f"기존 모델을 불러와서 추가 학습합니다. ({MODEL_PATH})")
except:
    print(" 기존 모델이 없어서 새로 학습을 시작합니다.")
    model = SAC(
        "CnnPolicy",
        env,
        learning_rate=3e-4,
        buffer_size=1000000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        train_freq=1,
        gradient_steps=1,
        verbose=1,
        tensorboard_log=LOG_DIR
    )

#  초기 속도 및 방향 변수
current_steering = 0.0  
current_speed = 0.0     

#  사람이 개입하는 정도를 조절하는 하이퍼파라미터
initial_alpha = 0.9  
min_alpha = 0.0  
decay_rate = 0.5  #  감소 속도 (조금 더 천천히 줄어들도록 변경)
max_human_steps = 1_000_000  # 100만 스텝 이후 자동 주행 전환

#  키입력을 통한 인간 개입
def get_human_action(original_action, step):
    global current_steering, current_speed
    
    keys = pygame.key.get_pressed()
    action = np.array(original_action, dtype=np.float32).reshape(-1)  

    steer_step = 0.1  
    speed_step = 0.05  
    brake_step = 0.1  # ✅ 브레이크 강도 증가
    steering_recovery = 0.05  

    # ✅ **조향 조정 (좌/우 방향키)**
    if keys[pygame.K_LEFT]:  
        current_steering -= steer_step  
        action[2] = min(0.3, action[2] + brake_step)  # ✅ 좌회전 시 브레이크 추가 적용
    if keys[pygame.K_RIGHT]:  
        current_steering += steer_step  
        action[2] = min(0.3, action[2] + brake_step)  # ✅ 우회전 시 브레이크 추가 적용

    # ✅ **가속 (위 방향키)**
    if keys[pygame.K_UP]:  
        current_speed += speed_step  
        action[2] = 0.0  # 🚀 가속 중에는 브레이크를 완전히 해제
        if current_steering > 0:
            current_steering = max(0, current_steering - steering_recovery)
        elif current_steering < 0:
            current_steering = min(0, current_steering + steering_recovery)

    # ✅ **브레이크 (아래 방향키)**
    if keys[pygame.K_DOWN]:  
        action[2] = 1.0  # 🚀 즉각적으로 최대 브레이크 적용
        current_speed *= 0.8  # 🚀 감속 비율 적용 (속도 감소)

    # ✅ 브레이크를 적용하지 않는 경우 점진적으로 감소
    if not keys[pygame.K_DOWN] and not keys[pygame.K_LEFT] and not keys[pygame.K_RIGHT]:
        action[2] = max(0.0, action[2] - 0.05)

    # ✅ 속도가 너무 작으면 0으로 설정 (완전 정지 방지)
    if current_speed < 0.02:  
        current_speed = 0.0

    # ✅ 값 범위 제한
    current_steering = np.clip(current_steering, -1.0, 1.0)
    current_speed = np.clip(current_speed, 0.0, 1.0)  
    action[2] = np.clip(action[2], 0.0, 1.0)  # 브레이크 값도 제한

    # ✅ 사람이 개입한 값과 SAC 모델 값의 혼합 비율 (alpha 적용)
    if step >= max_human_steps:
        alpha = 0.0  
    else:
        alpha = max(min_alpha, initial_alpha - decay_rate * (step / max_human_steps))

    action[0] = alpha * current_steering + (1 - alpha) * action[0]  # 조향 혼합
    action[1] = alpha * current_speed + (1 - alpha) * action[1]  # 속도 혼합
    action[2] = alpha * action[2] + (1 - alpha) * action[2]  # ✅ 브레이크도 혼합

    return action



# HIL 학습 루프 (300만 스텝)
obs = env.reset()
obs = obs.transpose(0, 3, 1, 2)  
done = False
total_timesteps = 3000000
step = 0
last_update_step = 0  #  마지막 학습이 이루어진 스텝 기록

while step < total_timesteps:
    pygame.event.pump()  

    human_override = False  
    action = model.predict(obs, deterministic=True)[0]  

    if any(pygame.key.get_pressed()):  
        action = get_human_action(action, step)  #  step 값을 함수에 전달
        human_override = True  

    action = np.array(action).reshape(1, -1)  

    # 환경 업데이트
    step_result = env.step(action)

    if len(step_result) == 4:  
        next_obs, reward, done, info = step_result
        terminated, truncated = done, False  
    elif len(step_result) == 5:  
        next_obs, reward, terminated, truncated, info = step_result
    else:
        raise ValueError(f"Unexpected number of return values from env.step(action): {len(step_result)}")

    done = terminated or truncated
    next_obs = next_obs.transpose(0, 3, 1, 2)  

    #  SAC 모델의 주행 데이터도 학습 데이터로 추가
    model.replay_buffer.add(
        np.array(obs),  
        np.array(next_obs),  
        np.array(action),  
        np.array([reward]),  
        np.array([terminated]),  
        [{}]  
    )

    #  사람이 한 번이라도 개입했으면 1000 스텝마다 학습 실행
    if human_override:
        last_update_step = step  #  개입한 마지막 스텝 기록
    
    if (step - last_update_step) >= 1000:  
        print(f"📢 Step {step}: Training for 1000 steps due to human intervention...")
        model.learn(total_timesteps=1000)
        last_update_step = step  #  학습 후 마지막 학습 스텝 갱신

    obs = next_obs  
    step += 1
    env.render()

    print(f"Step: {step}, Human Override: {human_override}, Action: {action}")

# 모델 저장
model.save(MODEL_PATH)
print(f"💾 학습이 완료되었습니다. 모델이 '{MODEL_PATH}'에 저장되었습니다.")

pygame.quit()
