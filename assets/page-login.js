import Vue from 'vue';
import './picker.js';
import { call } from './utils.js';
import tpl from './page-login.html';

Vue.component('Login', {
  template: tpl,
  data: function() {
    return {
      params: {
        username: '',
        password: '',
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        theme: 'base'
      },
      error: null,
      themes: window.data.themes,
      timezones: window.data.timezones
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

new Vue({
  el: '#app',
  template: '<login />'
});
