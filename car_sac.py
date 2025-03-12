import gymnasium as gym
from stable_baselines3 import SAC
import os

env = gym.make("CarRacing-v3", render_mode="human", continuous=True)

# 저장된 모델이 있는지 확인 후 불러오기
if os.path.exists("sac_CarRacing.zip"):
    model = SAC.load("sac_CarRacing", env=env)  # 기존 모델 불러오기
    print("✅ 기존 학습된 모델 불러와서 추가 학습 진행")
else:
    model = SAC("MlpPolicy", env, verbose=1)  # 새로운 모델 생성
    print("🚀 저장된 모델이 없어 새로운 모델을 학습 시작")

# 추가 학습 진행 (이전 학습 내용을 유지하며 학습)
model.learn(total_timesteps=100000, log_interval=4)

# 모델 저장 (학습된 내용 유지)
model.save("sac_CarRacing")

# 테스트 실행
obs, info = env.reset()
while True:
    action, _states = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        obs, info = env.reset()
