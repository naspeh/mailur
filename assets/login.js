import Vue from 'vue';
import Multiselect from 'vue-multiselect';
import { call } from './utils.js';
import tpl from './login.html';
import './login.css';

Vue.component('multiselect', Multiselect);

Vue.component('Login', {
  template: tpl,
  props: {
    timezones: { type: Array, required: true }
  },
  data: function() {
    return {
      params: {
        username: '',
        password: '',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
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

call('get', '/timezones').then(res => {
  new Vue({
    el: '#app',
    template: '<login :timezones="timezones" />',
    data: {
      timezones: res
    }
  });
});
