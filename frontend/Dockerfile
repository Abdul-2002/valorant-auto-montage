FROM node:20-alpine AS build

WORKDIR /app
COPY package.json /app/package.json

RUN npm install

COPY index.html vite.config.ts tsconfig.json /app/
COPY src /app/src

RUN npm run build


FROM node:20-alpine AS runtime

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

COPY package.json /app/package.json
RUN npm install --omit=dev

COPY server /app/server
COPY --from=build /app/dist /app/dist

EXPOSE 3000
CMD ["node", "server/index.js"]
