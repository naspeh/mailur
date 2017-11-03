import Vue from 'vue';

export default () => {
  window.app = new Vue({
    el: '#app',
    template: require('html-loader!./app.html'),
    data: {
      query: decodeURIComponent(location.hash.slice(1)) || 'all',
      showBodies: false,
      showThreads: false
    },
    methods: {
      get: function() {
        window.location.hash = this.query;
        this.$refs.msgs.get(
          this.showThreads ? '/api/threads' : '/api/msgs',
          this.query
        );
      }
    }
  });
};
