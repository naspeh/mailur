import Vue from 'vue';
import { call } from './utils.js';
import tpl from './login.html';
import './login.css';

Vue.component('Login', {
  template: tpl,
  data: function() {
    return {
      params: {
        username: '',
        password: '',
        offset: new Date().getTimezoneOffset() / 60,
        theme: 'base'
      },
      error: null,
      themes: window.themes
    };
  },
  methods: {
    send: function() {
      call('post', '/login', this.params).then(res => {
        if (res.errors) {
          this.error = res.errors[0];
          return;
        }
        window.location = res.url;
      });
    }
  }
});

new Vue({
  el: '#app',
  template: '<login />'
});
