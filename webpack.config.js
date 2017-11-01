const path = require('path');
const Package = require('./package.json')
const HtmlWebpackPlugin = require('html-webpack-plugin');
const CleanWebpackPlugin = require('clean-webpack-plugin');
const PrettierPlugin = require('prettier-webpack-plugin');

const dist = path.resolve(__dirname, 'assets/dist')

module.exports = {
  entry: {
    index: './assets/index.js'
  },
  plugins: [
    new PrettierPlugin(Package.prettier),
    new CleanWebpackPlugin([dist]),
    new HtmlWebpackPlugin({
      template: 'assets/index.html'
    })
  ],
  output: {
    filename: '[name].[hash].js',
    path: dist
  },
  resolve: {
    alias: {
      vue$: 'vue/dist/vue.esm.js'
    }
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        loader: 'babel-loader',
        exclude: /node_modules/
      },
      {
        test: /\.html$/,
        use: ['html-loader']
      }
    ]
  },
  devtool: '#eval-source-map'
};

if (process.env.NODE_ENV === 'production') {
  module.exports.devtool = '#source-map';
  // http://vue-loader.vuejs.org/en/workflow/production.html
  module.exports.plugins = (module.exports.plugins || []).concat([
    new webpack.DefinePlugin({
      'process.env': {
        NODE_ENV: '"production"'
      }
    }),
    new webpack.optimize.UglifyJsPlugin({
      sourceMap: true,
      compress: {
        warnings: false
      }
    }),
    new webpack.LoaderOptionsPlugin({
      minimize: true
    })
  ]);
}
