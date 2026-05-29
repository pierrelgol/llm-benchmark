#ifndef TOML_H
#define TOML_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum e_type {
        TOML_STRING,
        TOML_INT,
        TOML_FLOAT,
        TOML_BOOL,
        TOML_ARRAY,
        TOML_TABLE
} t_type;

typedef struct s_toml {
        char  *key;
        t_type type;
        union {
                char           *string;
                int64_t         integer;
                double          floating;
                bool            boolean;
                struct s_toml **array;
                struct s_toml **table;
        } value;
        size_t array_len;
        size_t table_len;
} t_toml;

t_toml *toml_parse(const char *content);
void    toml_free(t_toml *root);

#endif
