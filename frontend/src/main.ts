import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import './assets/styles/main.css';
import '@phosphor-icons/web/regular';
import '@phosphor-icons/web/bold';
import 'highlight.js/styles/atom-one-light.min.css';

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.mount('#app');
