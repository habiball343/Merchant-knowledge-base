<script setup>
import { onMounted, ref } from 'vue'
import ChatView from './components/ChatView.vue'
import LibraryView from './components/LibraryView.vue'
import ServiceStatus from './components/ServiceStatus.vue'
import { fetchHealth } from './lib/api.js'

const VIEWS = [
  { id: 'chat', label: '问答' },
  { id: 'library', label: '知识库' },
]

const view = ref('chat')
const health = ref(null)
const chat = ref(null)

async function refreshHealth() {
  try {
    health.value = await fetchHealth()
  } catch {
    health.value = { unreachable: true }
  }
}

function show(id) {
  view.value = id
  if (id === 'chat') chat.value?.refreshProducts()
}

onMounted(refreshHealth)
</script>

<template>
  <div class="app">
    <header class="masthead">
      <div class="brand">
        <h1>掌柜智库</h1>
        <p>商品资料问答</p>
      </div>
      <nav aria-label="页面">
        <button
          v-for="item in VIEWS"
          :key="item.id"
          type="button"
          :class="{ current: view === item.id }"
          :aria-current="view === item.id ? 'page' : undefined"
          @click="show(item.id)"
        >
          {{ item.label }}
        </button>
      </nav>
      <ServiceStatus :health="health" @refresh="refreshHealth" />
    </header>

    <main>
      <!-- 两个页面都保持挂载：切到知识库再回来，对话和正在生成的回答都还在 -->
      <ChatView v-show="view === 'chat'" ref="chat" @open-library="show('library')" />
      <LibraryView v-show="view === 'library'" :active="view === 'library'" @changed="chat?.refreshProducts()" />
    </main>
  </div>
</template>

<style scoped>
.app {
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.masthead {
  display: flex;
  align-items: stretch;
  gap: 28px;
  padding: 0 24px;
  background: var(--sheet);
  border-top: 4px solid var(--blue);
  border-bottom: 1px solid var(--rule-strong);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 12px 0;
}
.brand h1 {
  font-size: 21px;
  font-weight: 900;
  letter-spacing: 0.06em;
  color: var(--blue-deep);
}
.brand p {
  font-size: 13px;
  color: var(--ink-soft);
}

nav {
  display: flex;
  gap: 4px;
  margin-right: auto;
}
nav button {
  position: relative;
  padding: 0 14px;
  border: 0;
  background: none;
  font-size: 15px;
  color: var(--ink-soft);
}
nav button:hover {
  color: var(--blue);
}
nav button.current {
  color: var(--ink);
  font-weight: 800;
}
nav button.current::after {
  content: "";
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: -1px;
  height: 3px;
  background: var(--blue);
}

.masthead > :last-child {
  align-self: center;
}

main {
  min-height: 0;
}

@media (max-width: 720px) {
  .masthead {
    gap: 12px;
    padding: 0 14px;
  }
  .brand p {
    display: none;
  }
  .brand h1 {
    font-size: 18px;
  }
  nav button {
    padding: 0 8px;
  }
  nav button.current::after {
    left: 8px;
    right: 8px;
  }
}
</style>
