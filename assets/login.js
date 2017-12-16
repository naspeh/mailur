import Vue from 'vue';
import './select2.js';
import { call } from './utils.js';
import tpl from './login.html';

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
  mounted: function() {
    this.$el.querySelector('.login input').focus();
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
