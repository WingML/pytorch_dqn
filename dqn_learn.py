"""
    This file is copied/apdated from https://github.com/berkeleydeeprlcourse/homework/tree/master/hw3
"""
import sys
import pickle
import numpy as np
from collections import namedtuple
from itertools import count
import random
import collections
import copy
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.autograd as autograd

from Buffer import ReplayBuffer
from dqn_model import DQN
from torch.autograd import Variable

'''

1.初始化Q网络和target_Q网络(Q网络和targetQ网络在dqn_model.py中修改结构)
2.获得一个初始状态，以50%概率随机选取动作a,或者以50%概率由Q网络选取动作。e_greedy_select_action()函数
3.当前状态state下执行动作a（transition_function()函数）, 获取下一个状态next_state和奖励reward（reward_function()函数）
4.储存（s,a,r,s′,done）到经验池中,每一个看成一个样本。PS:buffer函数我已经写好
5.在经验池中选取一个批量的训练样本。
6.对于每一个训练样本，有y=r+γmax′atarget_Q(s′,a′)，也就是说，使用target_Q网络根据Bellman方程计算Q值。
  由于这里的y,r是相对于这个样本而言。因此，y实际上的意义是等于Q(s,a)，也就是我们训练Q网络要逼近的目标。
  # Note: done[i] is 1 if the next state corresponds to the end of an episode,in which case there is no Q-value 
    at the next state; at the end of an episode, only the current state reward contributes to the target
  不要问上面的那个公式是怎么来的，具体可以去看强化学习的推理公式，总归只要知道这是一个规定的更新公式就可以
7.计算损失函数：L=(Q−y)**2 
8.使用SGD更新Q网络以降低L。
9.target_Q = Q，即同步两个网络。
10.从步骤2开始重复直至收敛。

'''


# auxiliary_func
def random_displacement(state0): # 上下左右 -10，10，-1，1
    ''' Randomly generate users movement for next state '''
    ra = []
    for u in state0:
        # on the corner
        if u == 1:
            ra.append(random.choice([10,1]))
        elif u == 10:
            ra.append(random.choice([10,-1]))
        elif u == 91:
            ra.append(random.choice([-10,1]))
        elif u == 100:
            ra.append(random.choice([-10,-1]))
        # on the edge
        elif u < 11:
            ra.append(random.choice([10,-1,1]))
        elif u > 90:
            ra.append(random.choice([-10,-1,1]))
        elif u % 10 == 1:
            ra.append(random.choice([-10,10,1]))
        elif u % 10 == 0:
            ra.append(random.choice([-10,10,-1]))
        # insides
        else:
            ra.append(random.choice([-10,10,-1,1]))
    return ra

def e_greedy_select_action(state):
    '''
    动作选择函数，以50%概率随机选取动作a,或者以50%概率由Q网络选取动作。
    随机选择动作的目的是为了更多的探索有效空间。
    该函数需要根据我们的action进行更改
    '''
    sample = random.uniform(-1,1)
    if sample > 0:
        with torch.no_grad():
            return policy_net(state).max(1)[1].view(1, 1)
    else:
        return torch.tensor([[random.randrange(2)]], device=device, dtype=torch.long)

def transition_function(state, action):
    '''
    状态转移函数
    该函数输入为当前状态和动作，输出为下一个状态和终止字符（判断是否为终止状态 true or false）
    return next_state,done,flag
    '''
    #action为1-27某值
    state_t = copy.deepcopy(state)
    act = actions_list[action]
    sou_dst = []

    # transit node_loc
    for i, a in enumerate(act):
        sou_dst.append(a.find('1'))
        state_t[2][i] = node_loc[sou_dst[i]]

    # check if edge node meets the demand of two users
    # if not, no change on state and set flag = 0, thus negative reward
    if state_t[2][0] == state_t[2][1]:
        if state_t[3][0] + state_t[3][1] > 10:
            return state,0,0
    if state_t[2][0] == state_t[2][2]:
        if state_t[3][0] + state_t[3][2] > 10:
            return state,0,0
    if state_t[2][1] == state_t[2][2]:
        if state_t[3][1] + state_t[3][2] > 10:
            return state,0,0
    if state_t[2][0] == state_t[2][1] & state_t[2][0] == state_t[2][2]:
        if state_t[3][0] + state_t[3][1] + state_t[3][2]> 10:
            return state,0,0
    
    # transit user_loc
    state_t[0] = [state_t[0][j]+state_t[1][j] for j in range(3)]
    # generate new movement
    state_t[1] = random_displacement(state_t[0])
    return state_t,0,1

def reward_function(state, action, next_state, flag):
    '''
    奖励函数
    输入为当前状态，动作，下一个状态
    返回一个当前的奖惩值
    return reward
    '''
    # unfeasible displacement
    if flag == 0:
        return -9999, 0

    # changes of node_loc from state to next_state
    sou_dst = []
    for i, a in zip(state[2], action):
        sou_dst.append([i, a.find('1')])

    cost = 0
    for i in range(3):
        # expense of state = power(distance_u2n, 2) + communication delay of use_buff
        origin = ((state[0][i]%10-state[2][i]%10)**2+(state[0][i]//10-state[2][i]//10)**2) + state[3][i]/2
        # expense of next_state = change1 + change2, where
        # change1 = power(distance_u2n, 2) + communication delay of use_buff
        # change2 = power(distance_n2n, 2), i.e. expense of migration between nodes
        change1 = ((next_state[0][i]%10-next_state[2][i]%10)**2+(next_state[0][i]//10-next_state[2][i]//10)**2) + next_state[3][i]/2
        change2 = 0
        for j in sou_dst:
            change2 += ((node_loc[j[0]]%10-node_loc[j[1]]%10)**2+(node_loc[j[0]]//10-node_loc[j[1]]//10)**2)/5
        # return positive reward only when (expense of state > expense of next_state)
        cost += origin - change1 - change2
    return cost, change2

def optimize_model(batch, policy_net, target_net, optimizer_policy, criterion):
    states = torch.tensor(np.asarray([e[0] for e in batch]), device=device).float()
    states.requires_grad_()

    actions = torch.tensor(np.asarray([e[1] for e in batch]), device=device).float()
    actions.requires_grad = True

    rewards = torch.tensor(np.asarray([e[2] for e in batch]), device=device).float()
    rewards.requires_grad = True

    new_states = torch.tensor(np.asarray([e[3] for e in batch]), device=device).float()
    new_states.requires_grad = True

    dones = [e[4] for e in batch]

    not_done_mask = Variable(torch.from_numpy(1 - dones)).type(torch.cuda.FloatTensor)

    #根据梯度进行网络参数的更新
    current_Q_values = policy_net(states).gather(1, actions.unsqueeze(1))
    next_max_q = target_net(new_states).detach().max(1)[0]
    next_Q_values = not_done_mask * next_max_q
    target_Q_values = rewards + (GAMMA * next_Q_values)
    bellman_error = criterion(target_Q_values - current_Q_values)


    optimizer_policy.zero_grad()
    bellman_error.backward()
    optimizer_policy.step()

    #更新target policy
    new_actor_state_dict = collections.OrderedDict()
    for var_name in target_net.state_dict():
        new_actor_state_dict[var_name] = TAU * policy_net.state_dict()[var_name] + (1 - TAU) * \
                                         target_net.state_dict()[var_name]
        target_net.load_state_dict(new_actor_state_dict)

    return policy_net,target_net


#参数
BATCH_SIZE = 128
GAMMA = 0.999
EPS_START = 0.9
EPS_END = 0.05
EPS_DECAY = 200
TARGET_UPDATE = 10
TAU= 0.001

MAX_T = 1000
num_episodes = 50
learning_rate=0.01

buffer_size=100000
# node_capacity = 10 # capacity of each edge node
U_num=3
num_actions=27
actions = ['100', '010', '001']
actions_list = [[x,y,z] for x in actions for y in actions for z in actions]
node_loc = np.random.randint(0, 101, U_num).tolist()   #边缘节点位置 1-100号 (so we suppose that node_num == U_num???)

user_loc = np.random.randint(0, 101, U_num).tolist()   #用户位置 1-100号
user_dis = random_displacement(user_loc)   #用户未来位移 上下左右 -10，10，-1，1
use_buff = np.random.randint(3, 8, U_num).tolist()   #资源所需
state0 = [user_loc,
          user_dis,
          node_loc,
          use_buff]

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


#主程序部分

policy_net = DQN(U_num, num_actions).to(device)  #初始化Q网络
target_net = DQN(U_num, num_actions).to(device)  #初始化target_Q网络
target_net.load_state_dict(policy_net.state_dict())  #用Q网络的参数初始化target_Q网络
target_net.eval()
optimizer_policy = torch.optim.Adam(policy_net.parameters(), lr=learning_rate)  #定义优化器Adam，可以更换
buffer = ReplayBuffer(buffer_size)  #定义一个经验池  PS：经验池储存经验数据，后随机从经验池中抽取经验数据来训练更新网络参数 在Buffer.py中
criterion = torch.nn.MSELoss(reduction='sum')

# training
for i_episode in range(num_episodes):

    #state0 #获得一个初始化状态

    for t in count():
        # 选择动作
        action = e_greedy_select_action(state0)
        print("action selected by e_greedy is {}".format(action))
        # 利用状态转移函数，得到当前状态下采取当前行为得到的下一个状态，和下一个状态的终止情况
        state1, done, flag = transition_function(state0, action)
        # 利用奖励函数，获得当前的奖励值
        reward, cost_migration = reward_function(state0, action, state1, flag)
        # 将经验数据存储至buffer中
        buffer.add(state0, action, reward, state1, done)

        # exit an episode after MAX_T steps
        if t > MAX_T:
            break

        #当episode>10时进行网络参数更新，目的是为了让经验池中有较多的数据，使得训练较为稳定。
        if i_episode>10:

            # 从buffer中取出一批训练样本，训练数据batch由BATCH_SIZE参数决定
            batch = buffer.getBatch(BATCH_SIZE)

            policy_net, target_net=optimize_model(batch,policy_net,target_net,optimizer_policy,criterion)

        # 进入下一状态
        state0 = state1

# testing
long_term_rewards = []
long_term_cost_migrations = []
for i_episode in range(num_episodes):

    #state0 #获得一个初始化状态
    long_term_reward = 0
    long_term_cost_migration = 0

    for t in count():
        # 选择动作
        action = e_greedy_select_action(state0)
        print("action selected by e_greedy is {}".format(action))
        # 利用状态转移函数，得到当前状态下采取当前行为得到的下一个状态，和下一个状态的终止情况
        state1, done, flag = transition_function(state0, action)
        # 利用奖励函数，获得当前的奖励值
        reward, cost_migration = reward_function(state0, action, state1, flag)

        # record
        long_term_reward += reward
        long_term_cost_migration += cost_migration
        
        # 将经验数据存储至buffer中
        buffer.add(state0, action, reward, state1, done)

        # exit an episode after MAX_T steps
        if t >= MAX_T:
            long_term_reward /= t
            long_term_cost_migration /= t
            break

        # 进入下一状态
        state0 = state1

    long_term_rewards.append(long_term_reward)
    long_term_cost_migrations.append(long_term_cost_migration)

print('avg long-term reward: {}'.format(np.mean(long_term_rewards)))
print('avg long-term cost of migration: {}'.format(np.mean(long_term_cost_migrations)))