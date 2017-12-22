import Vue from 'vue';
import './picker.js';
import { call } from './utils.js';
import tpl from './login.html';

Vue.component('Login', {
  template: tpl,
  data: function() {
    return {
      params: {
        username: '',
        password: '',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        theme: window.data.current_theme
      },
      disabled: false,
      error: null,
      themes: window.data.themes,
      timezones: window.data.timezones
    };
  },
  mounted: function() {
    this.focus();
  },
  methods: {
    focus: function() {
      this.$refs.username.focus();
    },
    send: function() {
      this.disabled = true;
      this.error = null;
      call('post', '/login', this.params).then(res => {
        if (res.errors) {
          this.disabled = false;
          this.error = res.errors[0];
          this.$nextTick(() => this.focus());
          return;
        }
        let index = window.location.pathname.replace('login', '');
        window.location.replace(index);
      });
    }
  }
});

new Vue({
  el: '#app',
  template: '<login />'
});
